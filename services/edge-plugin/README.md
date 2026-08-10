# Edge Plugin (`aico_edge_plugin`)

Rust-based Proxy-Wasm Service Extension that detects AI crawlers at the Cloud CDN load balancer edge and rewrites their request path to route them to the AI Content Optimizer serving backend.

## Architecture & Detection Logic

1. **User-Agent Inspection**: Inspects incoming HTTP requests against a configurable list of AI crawler User-Agents (`GPTBot`, `ClaudeBot`, `PerplexityBot`, `Google-Extended`, etc.).
2. **Transparent Path Rewrite**: When a matching AI crawler is detected, the request `:path` is rewritten to `${ai_path_prefix}/...` (default `/_ai_optimized/...`), allowing the load balancer URL map to route the request directly to the optimized-content origin without modifying the external URL seen by the crawler.
3. **Loop Guard Protection**: Requests containing either the internal worker crawler User-Agent (`AIContentOptimizer/1.0`) or the serving-shim origin proxy header (`X-From-LLM-Optimizer`) are bypassed automatically to prevent routing loops.
4. **Human Traffic Bypass**: Normal web browsers and non-AI requests pass through completely unchanged with minimal latency (`< 1ms`).

## Building from Source (Optional for Custom Compilations)

The Terraform module uses pre-compiled, published container images by default. If you are modifying the Rust source code and compiling custom WebAssembly binaries:

```bash
source "$HOME/.cargo/env"
rustup target add wasm32-wasip1
cargo build --release --target wasm32-wasip1
# Compiled binary: target/wasm32-wasip1/release/aico_edge_plugin.wasm
```

### Packaging as an OCI WasmPlugin Image

```bash
mkdir -p package && cp -f target/wasm32-wasip1/release/aico_edge_plugin.wasm package/plugin.wasm
printf 'FROM scratch\nCOPY plugin.wasm plugin.wasm\n' > package/Dockerfile
docker build --no-cache --platform wasm -t REGISTRY/aico-edge-plugin:v1 package/
docker push REGISTRY/aico-edge-plugin:v1
```
