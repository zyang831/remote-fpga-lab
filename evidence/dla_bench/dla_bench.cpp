// Sync batch-1 latency of a precompiled CoreDLA graph (HETERO:FPGA,CPU), same method as cpu_bench.
// Usage: dla_bench plugins.xml graph.bin model.arch warmup runs   -> one line per timed run: microseconds.
#include <openvino/openvino.hpp>
#include "dla_plugin_config.hpp"
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iterator>
#include <random>
#include <sstream>
int main(int argc, char** argv) {
  if (argc != 6) { fprintf(stderr, "usage: %s plugins.xml graph.bin model.arch warmup runs\n", argv[0]); return 2; }
  ov::Core core(argv[1]);
  core.set_property("FPGA", {{DLIAPlugin::properties::arch_path.name(), std::string(argv[3])}});
  core.set_property("FPGA", {{DLIAPlugin::properties::cpu_used.name(), true}});
  std::ifstream in(argv[2], std::ios::binary);  // leading NUL-terminated device name, then the blob (as in dla-server)
  std::string dev; for (char c; in.get(c) && c != '\0';) dev += c;
  std::string blob((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
  std::istringstream s(blob); blob.clear(); blob.shrink_to_fit();
  auto cm = core.import_model(s, dev, {});
  auto req = cm.create_infer_request();
  ov::Tensor t = req.get_input_tensor();
  std::mt19937 g(1); std::uniform_real_distribution<float> d(0.f, 255.f);
  float* p = t.data<float>(); for (size_t i = 0; i < t.get_size(); i++) p[i] = d(g);
  for (int i = 0; i < atoi(argv[4]); i++) req.infer();
  for (int i = 0; i < atoi(argv[5]); i++) {
    auto t0 = std::chrono::steady_clock::now(); req.infer();
    printf("%lld\n", (long long)std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - t0).count());
  }
}
