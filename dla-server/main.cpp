// dla-server: persistent CoreDLA classifier for the remote lab.
//
// Imports one precompiled graph (graph.bin) once (~70 s, ~475 MB peak), then
// loops: every image file that appears in <spool>/inbox is centre-cropped to a
// square and resized to the graph input, run through HETERO:FPGA,CPU, and
// answered with <spool>/results/<name>.json {top5:[{index,label,prob}], latency_ms};
// the image moves to <spool>/done. Labels come from categories.txt (one per line,
// count must equal the output dim). Input contract: centre square crop, resize,
// RGB, f32 NCHW, no mean/scale (folded into the graph).
//
// Live camera: when the model's .arch is the camera bitstream's (CAMERA_ARCH),
// a thread keeps the IMX519 -> cam_msgdma ring free-running at 60 fps. A two-stage
// display thread debayers the newest frame to 480x270 (DLA_LIVE_DECIM=1: 960x540, ~0.7 % torn
// frames vs ~0.3 %) at DLA_LIVE_FPS (default 30) and publishes it as
// <spool>/results/live.jpg (~11 KB);
// whenever the inbox is empty the inference loop classifies the newest of those
// and writes live.json, so the picture never waits for the DLA (~4 Hz).
// Uploaded files always go first. Sensor exposure/gain: env DLA_CAM_EXPOSURE
// (lines, default 1147) and DLA_CAM_GAIN (code, default 850; tuned indoors).
//
//   dla-server <model_dir> <spool_dir> [plugins.xml]
//   model_dir: graph.bin, categories.txt, exactly one *.arch
#include <openvino/openvino.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include "dla_plugin_config.hpp"
#include "jpeg/jpeglib.h"
extern "C" {
#include "cam/regmap.h"
#include "cam/mmio.h"
#include "cam/altera_i2c.h"
#include "cam/imx519.h"
#include "cam/imx519_modes.h"
#include "cam/cam_msgdma.h"
#include "cam/cam_frame.h"
}

#include <algorithm>
#include <atomic>
#include <cstdlib>
#include <cstring>
#include <chrono>
#include <condition_variable>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <mutex>
#include <pthread.h>
#include <numeric>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace fs = std::filesystem;
static const char* DEVICE = "HETERO:FPGA,CPU";
// ponytail: the arch name is the only signal that the fabric has the camera
// blocks; the older bitstreams leave 0x2002_2000+ unmapped and touching that
// can SError. A second camera bitstream needs adding here.
static const char* CAMERA_ARCH = "AGX5_Small_k16c16_sb20480";
static const unsigned FRAME_W = IMX519_MODE_1920x1080_WIDTH, FRAME_H = IMX519_MODE_1920x1080_HEIGHT;
static const size_t FRAME_BYTES = IMX519_MODE_1920x1080_FRAME_BYTES;
static const unsigned SLOTS = CAM_FRAME_SIZE / FRAME_BYTES;  // 16

// Frame k lands in slot k % SLOTS; seq = frames completed, so the newest is in
// slot (seq-1) % SLOTS. The capture thread arms frame m as soon as seq == m,
// and frame seq-1+SLOTS reuses the newest frame's slot: a copy taken at seq is
// intact iff the counter read after the copy has not reached seq-1+SLOTS.
constexpr unsigned ring_slot(uint64_t seq, unsigned slots) { return (unsigned)((seq - 1) % slots); }
constexpr bool ring_intact(uint64_t seq, uint64_t seq_after, unsigned slots) { return seq_after - seq <= slots - 2; }
static_assert(ring_slot(1, 15) == 0 && ring_slot(15, 15) == 14 && ring_slot(16, 15) == 0);
static_assert(ring_intact(5, 5, 15) && ring_intact(5, 18, 15) && !ring_intact(5, 19, 15));

struct Camera {
  mmio i2c_win{}, ring{};
  altera_i2c i2c{};
  cam_msgdma dma{};
  std::atomic<uint64_t> seq{0};
  std::atomic<uint64_t> overruns{0};
};

// Newest debayered frame, handed from display_loop to the inference loop.
struct LiveFrame {
  std::mutex m;
  cv::Mat rgb;
  uint64_t seq = 0;
};

static int env_int(const char* name, int def) {
  const char* v = std::getenv(name);
  return v && *v ? std::atoi(v) : def;
}

// Returns false (camera left off, file mode only) on any bring-up failure.
static bool camera_open(Camera& c) {
  if (mmio_open(&c.i2c_win, CAM_I2C_BASE, 0x40)) return std::cerr << "camera: map i2c: " << strerror(errno) << "\n", false;
  uint16_t id = 0;
  if (i2c_init(&c.i2c, &c.i2c_win, 100000000u, 100000u) || imx519_identify(&c.i2c, &id) != I2C_OK || id != IMX519_CHIP_ID)
    return std::cerr << "camera: IMX519 not found (id " << id << ")\n", false;
  if (mmio_open(&c.ring, CAM_FRAME_PHYS, (size_t)SLOTS * FRAME_BYTES) || cam_msgdma_open(&c.dma))
    return std::cerr << "camera: map ring/msgdma: " << strerror(errno) << "\n", false;
  if (imx519_stream_start_1080p60(&c.i2c) != I2C_OK) return std::cerr << "camera: stream start failed\n", false;
  const int exp = env_int("DLA_CAM_EXPOSURE", 1147), gain = env_int("DLA_CAM_GAIN", 850);
  imx519_wr8(&c.i2c, 0x0202, (uint8_t)(exp >> 8));
  imx519_wr8(&c.i2c, 0x0203, (uint8_t)exp);
  imx519_wr8(&c.i2c, 0x0204, (uint8_t)(gain >> 8));
  imx519_wr8(&c.i2c, 0x0205, (uint8_t)gain);
  cam_msgdma_reset(&c.dma);
  std::cerr << "camera: IMX519 streaming 1080p60, exposure " << exp << " gain " << gain << ", ring "
            << SLOTS << " slots at 0x" << std::hex << CAM_FRAME_PHYS << std::dec << "\n";
  return true;
}

// Free-running: re-arm the next slot the moment a frame completes (the gate
// only starts on a frame head, so any idle DMA time costs a whole frame).
static void capture_loop(Camera& c) {
  uint64_t n = 0;
  cam_msgdma_start_frame(&c.dma, CAM_FRAME_PHYS, FRAME_BYTES);
  for (;;) {
    if (int w = cam_msgdma_wait_frame(&c.dma, 2000)) {
      std::cerr << "camera: frame " << n << " wait failed (" << w << "), live view stopped\n";
      return;
    }
    ++n;
    cam_msgdma_start_frame(&c.dma, CAM_FRAME_PHYS + (n % SLOTS) * FRAME_BYTES, FRAME_BYTES);
    c.seq.store(n, std::memory_order_release);
  }
}

static void write_atomic(const fs::path& p, const std::string& body) {
  fs::path tmp = p.string() + ".tmp";
  { std::ofstream f(tmp); f << body; }
  fs::rename(tmp, p);
}

// The board OpenCV has no JPEG codec, so this uses the rootfs libjpeg-turbo
// (shipped beside the binary; headers vendored in jpeg/).
static std::string jpeg_encode(const cv::Mat& rgb, int quality) {
  jpeg_compress_struct ci;
  jpeg_error_mgr err;
  ci.err = jpeg_std_error(&err);
  jpeg_create_compress(&ci);
  unsigned char* buf = nullptr;
  unsigned long len = 0;
  jpeg_mem_dest(&ci, &buf, &len);
  ci.image_width = rgb.cols, ci.image_height = rgb.rows, ci.input_components = 3, ci.in_color_space = JCS_RGB;
  jpeg_set_defaults(&ci);
  jpeg_set_quality(&ci, quality, TRUE);
  ci.dct_method = JDCT_IFAST;  // live preview: speed over the last bit of DCT accuracy
  jpeg_start_compress(&ci, TRUE);
  while (ci.next_scanline < ci.image_height) {
    JSAMPROW row = (JSAMPROW)rgb.ptr(ci.next_scanline);
    jpeg_write_scanlines(&ci, &row, 1);
  }
  jpeg_finish_compress(&ci);
  jpeg_destroy_compress(&ci);
  std::string out((const char*)buf, len);
  free(buf);
  return out;
}

// Paced at `fps`: copy the newest ring slot out of the uncached ring (~28 ms); a
// second thread debayers it, hands it to inference and publishes live.jpg (~9 ms at
// 480x270, ~20 at 960x540). Two stages so each frame's copy overlaps the previous frame's debayer +
// JPEG. The copy stays on one core: two cores reading the ring at once starve the
// camera DMA of DDR bandwidth and ~7 % of frames tear (shifted, wrong Bayer phase).
// Runs beside inference, so the picture keeps its own rate.
// decim: Bayer cells averaged per side of an output pixel (2 -> 480x270, 1 -> 960x540).
static void display_loop(Camera& c, LiveFrame& lf, fs::path results, int fps, unsigned decim) {
  // ponytail: cpu_capacity reads 1024 on all four cores (no DT capacities), so the
  // scheduler parks this on an A55 (cpu0-1) as often as an A76 (cpu2-3), and the
  // uncached copy + debayer take 97 ms there vs 32 ms. Pinned to the A76s (the second
  // stage inherits it); read "CPU part : 0xd0b" from /proc/cpuinfo if another board
  // layout ever runs this.
  cpu_set_t big;
  CPU_ZERO(&big);
  CPU_SET(2, &big);
  CPU_SET(3, &big);
  pthread_setaffinity_np(pthread_self(), sizeof big, &big);
  // Three buffers: the copy fills `mine`, swaps it into `pending`; stage two swaps
  // `pending` into its own `work`. Only pointers move, under `m`.
  std::vector<uint16_t> mine(FRAME_BYTES / 2), pending(FRAME_BYTES / 2);
  uint64_t pending_seq = 0;
  bool fresh = false;
  std::mutex m;
  std::condition_variable ready;
  std::thread([&, decim] {
    std::vector<uint16_t> work(FRAME_BYTES / 2);
    cv::Mat rgb(FRAME_H / (2 * decim), FRAME_W / (2 * decim), CV_8UC3);
    for (;;) {
      uint64_t n;
      {
        std::unique_lock<std::mutex> g(m);
        ready.wait(g, [&] { return fresh; });
        work.swap(pending);
        n = pending_seq, fresh = false;
      }
      cam_frame_to_rgb8(work.data(), FRAME_W, FRAME_H, decim, rgb.data);
      { std::lock_guard<std::mutex> g(lf.m); rgb.copyTo(lf.rgb); lf.seq = n; }
      write_atomic(results / "live.jpg", jpeg_encode(rgb, 80));
    }
  }).detach();  // display_loop never returns, so the captured locals outlive it
  const auto period = std::chrono::microseconds(1000000 / std::max(fps, 1));
  auto next = std::chrono::steady_clock::now();
  uint64_t last = 0;
  for (;;) {
    std::this_thread::sleep_until(next);
    next = std::max(next + period, std::chrono::steady_clock::now());
    const uint64_t n = c.seq.load(std::memory_order_acquire);
    if (n == last) continue;
    last = n;
    std::memcpy(mine.data(), (const void*)(c.ring.base + (size_t)ring_slot(n, SLOTS) * FRAME_BYTES), FRAME_BYTES);
    if (!ring_intact(n, c.seq.load(std::memory_order_acquire), SLOTS)) { ++c.overruns; continue; }
    {
      std::lock_guard<std::mutex> g(m);
      mine.swap(pending);
      pending_seq = n, fresh = true;
    }
    ready.notify_one();
  }
}

static std::string json_escape(const std::string& s) {
  std::string o;
  for (char c : s) {
    if (c == '"' || c == '\\') o += '\\', o += c;
    else if ((unsigned char)c < 0x20) o += ' ';
    else o += c;
  }
  return o;
}

static std::vector<std::string> read_categories(const fs::path& p) {
  std::ifstream f(p);
  if (!f) throw std::runtime_error("cannot open " + p.string());
  std::vector<std::string> v;
  for (std::string line; std::getline(f, line);) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    v.push_back(line);
  }
  while (!v.empty() && v.back().empty()) v.pop_back();  // trailing blank line
  return v;
}

static fs::path find_arch(const fs::path& dir) {
  for (auto& e : fs::directory_iterator(dir))
    if (e.path().extension() == ".arch") return e.path();
  throw std::runtime_error("no .arch file in " + dir.string());
}

// dla_benchmark main.cpp:960-990: leading NUL-terminated device name, then the blob.
static ov::CompiledModel import_graph(ov::Core& core, const fs::path& graph) {
  std::ifstream in(graph, std::ios::binary);
  if (!in) throw std::runtime_error("cannot open " + graph.string());
  std::string dev;
  for (char c; in.get(c) && c != '\0';) dev += c;
  if (dev != DEVICE) throw std::runtime_error("graph.bin is for device '" + dev + "', not " + DEVICE);
  std::string blob((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
  in.close();
  std::istringstream s(blob);
  blob.clear(); blob.shrink_to_fit();  // ~150 MB; the stream owns its own copy
  return core.import_model(s, DEVICE, {});
}

static void fill_input(ov::Tensor& t, const cv::Mat& bgr) {
  const auto shape = t.get_shape();  // [1,3,H,W]
  const int H = (int)shape[2], W = (int)shape[3];
  // Centre square of the shorter side first, so a 16:9 live frame is not squashed
  // (same crop as training/common.py center_square).
  const int s = std::min(bgr.cols, bgr.rows);
  cv::Mat rgb;
  cv::cvtColor(bgr(cv::Rect((bgr.cols - s) / 2, (bgr.rows - s) / 2, s, s)), rgb, cv::COLOR_BGR2RGB);
  if (rgb.rows != H || rgb.cols != W) cv::resize(rgb, rgb, cv::Size(W, H));
  float* d = t.data<float>();
  const size_t plane = (size_t)H * W;
  for (int y = 0; y < H; ++y) {
    const uint8_t* row = rgb.ptr<uint8_t>(y);
    for (int x = 0; x < W; ++x)
      for (int c = 0; c < 3; ++c) d[c * plane + (size_t)y * W + x] = row[x * 3 + c];
  }
}

// Runs one image through the graph; returns the JSON body (no newline).
static std::string classify(ov::InferRequest& req, ov::Tensor& in, const cv::Mat& bgr,
                            const std::vector<std::string>& categories, const std::string& name) {
  const size_t n_out = categories.size();
  std::ostringstream js;
  fill_input(in, bgr);
  auto t1 = std::chrono::steady_clock::now();
  req.infer();
  double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t1).count();
  const float* p = req.get_output_tensor().data<const float>();
  std::vector<size_t> idx(n_out);
  std::iota(idx.begin(), idx.end(), 0);
  std::partial_sort(idx.begin(), idx.begin() + std::min<size_t>(5, n_out), idx.end(),
                    [p](size_t a, size_t b) { return p[a] > p[b]; });
  js << "{\"top5\":[";
  for (size_t i = 0; i < std::min<size_t>(5, n_out); ++i)
    js << (i ? "," : "") << "{\"index\":" << idx[i] << ",\"label\":\"" << json_escape(categories[idx[i]])
       << "\",\"prob\":" << p[idx[i]] << "}";
  js << "],\"latency_ms\":" << ms << "}";
  if (name != "live")  // ~4 Hz; keep it out of the journal
    std::cerr << name << " -> " << categories[idx[0]] << " (" << p[idx[0]] << ") " << ms << " ms\n";
  return js.str();
}

int main(int argc, char** argv) {
  if (argc < 3) { std::cerr << "usage: dla-server <model_dir> <spool_dir> [plugins.xml]\n"; return 2; }
  const fs::path model_dir = argv[1], spool = argv[2];
  const fs::path plugins = argc > 3 ? fs::path(argv[3]) : fs::path(argv[0]).parent_path() / "plugins.xml";
  const fs::path inbox = spool / "inbox", done = spool / "done", results = spool / "results";
  for (auto& d : {inbox, done, results}) fs::create_directories(d);

  try {
    auto categories = read_categories(model_dir / "categories.txt");
    ov::Core core(plugins.string());
    core.set_property("FPGA", {{DLIAPlugin::properties::arch_path.name(), find_arch(model_dir).string()}});
    core.set_property("FPGA", {{DLIAPlugin::properties::cpu_used.name(), true}});

    auto t0 = std::chrono::steady_clock::now();
    ov::CompiledModel model = import_graph(core, model_dir / "graph.bin");
    std::cerr << "import took " << std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count() << " s\n";

    ov::InferRequest req = model.create_infer_request();
    ov::Tensor in = req.get_input_tensor();
    const auto out_shape = model.output().get_shape();
    const size_t n_out = std::accumulate(out_shape.begin(), out_shape.end(), (size_t)1, std::multiplies<size_t>());
    if (in.get_shape().size() != 4 || in.get_shape()[1] != 3 || in.get_element_type() != ov::element::f32)
      throw std::runtime_error("unexpected input " + in.get_shape().to_string() + " " + in.get_element_type().to_string());
    if (categories.size() != n_out)
      throw std::runtime_error("categories.txt has " + std::to_string(categories.size()) +
                               " lines but the graph outputs " + std::to_string(n_out));
    std::cerr << "ready: input " << in.get_shape() << ", " << n_out << " classes, watching " << inbox << "\n";
    write_atomic(spool / "ready", std::to_string(n_out) + "\n");

    Camera cam;
    const bool live = find_arch(model_dir).stem() == CAMERA_ARCH && camera_open(cam);
    LiveFrame lf;
    if (live) {
      std::thread(capture_loop, std::ref(cam)).detach();
      std::thread(display_loop, std::ref(cam), std::ref(lf), results, env_int("DLA_LIVE_FPS", 30), (unsigned)std::max(1, env_int("DLA_LIVE_DECIM", 2))).detach();
    }
    cv::Mat rgb, bgr_live;
    uint64_t last = 0;
    auto t_last = std::chrono::steady_clock::now();

    for (;;) {
      bool idle = true;
      for (auto& e : fs::directory_iterator(inbox)) {
        if (!e.is_regular_file() || e.path().filename().string()[0] == '.') continue;
        idle = false;
        const fs::path img = e.path();
        const std::string name = img.filename().string();
        cv::Mat bgr = cv::imread(img.string(), cv::IMREAD_COLOR);
        std::string js = bgr.empty() ? "{\"error\":\"cannot decode image\"}" : classify(req, in, bgr, categories, name);
        fs::rename(img, done / name);
        write_atomic(results / (name + ".json"), js + "\n");
      }
      uint64_t n = last;
      if (idle && live) {
        std::lock_guard<std::mutex> g(lf.m);
        if (lf.seq != last) n = lf.seq, lf.rgb.copyTo(rgb);
      }
      if (n != last) {
        cv::cvtColor(rgb, bgr_live, cv::COLOR_RGB2BGR);
        std::string js = classify(req, in, bgr_live, categories, "live");
        auto t = std::chrono::steady_clock::now();
        const double fps = 1.0 / std::chrono::duration<double>(t - t_last).count();
        t_last = t;
        js.pop_back();  // reopen the object to append live stats
        js += ",\"frame\":" + std::to_string(n) + ",\"infer_fps\":" + std::to_string(fps) +
              ",\"skipped\":" + std::to_string(n - last - 1) + ",\"overruns\":" + std::to_string(cam.overruns.load()) + "}";
        write_atomic(results / "live.json", js + "\n");
        last = n;
        idle = false;
      }
      if (idle) std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
  } catch (const std::exception& e) {
    std::cerr << "dla-server: " << e.what() << "\n";
    return 1;
  }
}
