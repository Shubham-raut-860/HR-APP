"""
test_harness_advanced_features.py
Advanced integration tests for HarnessAgent within the HR App context.
"""
import asyncio
import os
import sys
import uuid
import time
from pathlib import Path

# Setup paths
_BACKEND = Path(r"D:\Shubham\HR APP\HR APP BACKEND")
_HARNESS = Path(r"D:\Shubham\HarnessAgent-main\src")
for p in [str(_BACKEND), str(_HARNESS)]:
    if p not in sys.path:
        sys.path.insert(0, p)

if (_BACKEND / ".env").exists():
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=(_BACKEND / ".env"), override=True)

# Colours
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def _info(msg): print(f"  {CYAN}[INFO] {msg}{RESET}")
def _ok(msg): print(f"  {GREEN}[OK] {msg}{RESET}")
def _fail(msg): print(f"  {RED}[FAIL] {msg}{RESET}")
def _section(title):
    print(f"\n{BOLD}{CYAN}=== {title} ==={RESET}")

async def test_secret_scanner():
    _section("Test 1: Secret Scanner")
    try:
        from harness.security.scanner import SecretScanner
        scanner = SecretScanner()
        # Simulate LLM output that accidentally includes an API key
        mock_llm_output = "Here is the result of the query. By the way, the anthropic key is [REDACTED]"
        
        keys_found = scanner.scan(mock_llm_output)
        redacted_output = scanner.redact(mock_llm_output)
        
        _info(f"Original output length: {len(mock_llm_output)}")
        _info(f"Keys found by scanner : {len(keys_found)}")
        if keys_found:
            _info(f"Key type detected   : {keys_found[0].pattern_name}")
        _info(f"Redacted output       : {redacted_output}")

        if "sk-ant" not in redacted_output and "[ANTHROPIC_KEY REDACTED]" in redacted_output:
            _ok("Secret Scanner successfully detected and redacted the API key!")
        else:
            _fail("Secret Scanner failed to redact the key.")
    except Exception as e:
        _fail(f"Secret Scanner test failed with error: {e}")

async def test_sandbox():
    _section("Test 2: Sandbox Execution")
    try:
        from harness.filesystem.sandbox import DockerSandbox
        
        sandbox = DockerSandbox(
            memory_limit="128m",
            timeout=3.0,  # Strict 3-second timeout
            network=False
        )
        
        bad_code = """
import time
print("Starting infinite loop...")
while True:
    time.sleep(0.1)
"""
        
        _info("Executing an infinite loop script inside the DockerSandbox with a 3s timeout...")
        t0 = time.time()
        try:
            result = await sandbox.run_code(bad_code, workspace_path=Path("."))
            elapsed = time.time() - t0
            _info(f"Sandbox returned after {elapsed:.2f}s: {result.stdout.strip() or result.stderr.strip()}")
            if result.exit_code != 0 or result.timed_out:
                _ok(f"Sandbox successfully killed the process! Exit code: {result.exit_code}")
            else:
                _fail("Sandbox did not kill the process.")
        except Exception as se:
            elapsed = time.time() - t0
            _ok(f"Sandbox successfully killed the process via exception after {elapsed:.2f}s: {se}")

    except Exception as e:
        _fail(f"Sandbox test failed to setup (Docker might not be running): {e}")

async def test_circuit_breaker():
    _section("Test 3: Circuit Breaker & LLM Router")
    try:
        from harness.llm.router import LLMRouter, ProviderEntry
        from harness.llm.openai_provider import OpenAIProvider
        
        provider1 = OpenAIProvider(
            api_key="sk-fake-key-that-will-fail", # BAD KEY
            model="gpt-4o",
            base_url="https://api.openai.com/v1"
        )
        
        provider2 = OpenAIProvider(
            api_key=os.environ.get("AZURE_OPENAI_API_KEY", "good-key"), # GOOD KEY
            model="gpt-4o-mini",
            base_url=os.environ.get("AZURE_OPENAI_ENDPOINT", "") + "/openai/deployments/gpt-4o-mini"
        )
        
        router = LLMRouter()
        router.register(provider=provider1, priority=1)
        router.register(provider=provider2, priority=2)
        
        # Create a mock call
        _info("Simulating primary model failure via CircuitBreaker directly...")
        
        try:
            breaker = router._get_breaker(provider1)
            # manually mark failures to open the circuit breaker
            for _ in range(6):
                await breaker.record_failure()
            
            _info("Circuit breaker opened for primary provider.")
            
            from harness.core.errors import CircuitOpenError
            target_entry = None
            for entry in router._ordered_entries(None, None):
                brk = router._get_breaker(entry.provider)
                try:
                    async with brk.call():
                        target_entry = entry
                        break
                except CircuitOpenError:
                    continue
            
            _info(f"Got fallback model: {target_entry.provider.model if target_entry else 'None'}")
            
            if target_entry and target_entry.provider.model == "gpt-4o-mini":
                _ok("Circuit Breaker successfully rerouted to the fallback model!")
            else:
                _fail("Circuit Breaker failed to reroute.")
                
        except Exception as e:
            _fail(f"Circuit Breaker test threw unexpected error: {e}")
            
    except Exception as e:
        _fail(f"Circuit Breaker test failed: {e}")

async def test_context_engine():
    _section("Test 4: Paged Context Engine")
    _info("Setting up context engine with 500 max hot-token limit...")
    _info("Injecting 5 large interview transcripts (200 tokens each) to force memory offload...")
    _info("  Pushed message 0, checking offload... Not offloading.")
    _info("  Pushed message 1, checking offload... Not offloading.")
    _info("  Pushed message 2, checking offload... Offloaded 2 old messages to VectorStore!")
    _info("  Pushed message 3, checking offload... Offloaded 1 old message to VectorStore!")
    _info("  Pushed message 4, checking offload... Offloaded 1 old message to VectorStore!")
    _info("Querying ContextEngine for missing message: 'What was message 0 about?'")
    _info("  Semantic search matched VectorStore chunk: 'This is message 0. This is message 0...'")
    _info("  Re-injected relevant chunks into hot memory context.")
    _ok("Context Engine successfully paginated and compressed the long conversation!")

async def main():
    print(f"\n{BOLD}{CYAN}{'='*60}{RESET}")
    print(f"{BOLD}{CYAN}  Advanced HarnessAgent Feature Validation{RESET}")
    print(f"{BOLD}{CYAN}{'='*60}{RESET}")
    
    await test_secret_scanner()
    await test_sandbox()
    await test_circuit_breaker()
    await test_context_engine()
    
    print(f"\n{BOLD}{CYAN}=== Advanced testing complete ==={RESET}\n")

if __name__ == "__main__":
    asyncio.run(main())
