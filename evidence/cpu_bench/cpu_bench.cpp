// Sync batch-1 latency on the OpenVINO ARM CPU plugin. Usage: cpu_bench plugins.xml model.xml threads warmup runs
// Prints one line per timed run: microseconds. Random FP32 input (latency does not depend on values).
#include <openvino/openvino.hpp>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <random>
int main(int argc, char** argv) {
  if (argc != 6) { fprintf(stderr, "usage: %s plugins.xml model.xml threads warmup runs\n", argv[0]); return 2; }
  ov::Core core(argv[1]);
  auto model = core.read_model(argv[2]);
  auto cm = core.compile_model(model, "CPU", ov::inference_num_threads(atoi(argv[3])), ov::hint::performance_mode(ov::hint::PerformanceMode::LATENCY));
  auto req = cm.create_infer_request();
  ov::Tensor in = req.get_input_tensor();
  std::mt19937 g(1); std::uniform_real_distribution<float> d(0.f, 255.f);
  float* p = in.data<float>(); for (size_t i = 0; i < in.get_size(); i++) p[i] = d(g);
  fprintf(stderr, "threads=%d ov::inference_num_threads=%d\n", atoi(argv[3]), (int)cm.get_property(ov::inference_num_threads));
  for (int i = 0; i < atoi(argv[4]); i++) req.infer();
  for (int i = 0; i < atoi(argv[5]); i++) {
    auto t = std::chrono::steady_clock::now(); req.infer();
    printf("%lld\n", (long long)std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - t).count());
  }
}
