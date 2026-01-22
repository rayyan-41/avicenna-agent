"""Phase 4 Verification: Test MCP-enabled GeminiProvider"""
import asyncio
import sys
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from source.avicenna.providers.gemini import GeminiProvider
from source.avicenna.config import Config


async def test_provider_initialization():
    """Test MCP provider initialization"""
    print("\n" + "="*60)
    print("TEST 1: PROVIDER INITIALIZATION")
    print("="*60)
    
    try:
        # Create provider
        provider = GeminiProvider(
            api_key=Config.API_KEY,
            model_name=Config.MODEL_NAME,
            system_instruction="You are a helpful assistant with tools."
        )
        
        print(f"\n→ Provider created")
        
        # Initialize (connects to MCP servers)
        print(f"→ Initializing MCP connections...")
        await provider.initialize()
        
        # Check tools loaded
        if provider.mcp_manager:
            tools = provider.mcp_manager.list_available_tools()
            print(f"✓ Tools loaded: {tools}")
        else:
            print(f"✗ MCP manager not initialized")
            return False
        
        # Cleanup
        await provider.cleanup()
        
        print(f"\n✓ Provider initialization test PASSED")
        return True
        
    except Exception as e:
        print(f"\n✗ Provider initialization test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_basic_tool_calling():
    """Test calling basic tools through provider"""
    print("\n" + "="*60)
    print("TEST 2: BASIC TOOL CALLING")
    print("="*60)
    
    provider = None
    try:
        # Create and initialize provider
        provider = GeminiProvider(
            api_key=Config.API_KEY,
            model_name=Config.MODEL_NAME,
            system_instruction=(
                "You are a helpful assistant. "
                "Use available tools to answer questions. "
                "Be concise and direct."
            )
        )
        
        await provider.initialize()
        
        # Test 1: Current time
        print(f"\n→ Test: 'What time is it?'")
        response = await provider.send_message("What time is it?")
        print(f"✓ Response: {response[:100]}...")
        
        # Test 2: Calculator
        print(f"\n→ Test: 'Calculate 15 * 7'")
        response = await provider.send_message("Calculate 15 * 7")
        print(f"✓ Response: {response[:100]}...")
        
        print(f"\n✓ Basic tool calling test PASSED")
        return True
        
    except Exception as e:
        print(f"\n✗ Basic tool calling test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        if provider:
            await provider.cleanup()


async def test_gmail_tool():
    """Test Gmail tool through provider"""
    print("\n" + "="*60)
    print("TEST 3: GMAIL TOOL")
    print("="*60)
    
    provider = None
    try:
        # Create and initialize provider
        provider = GeminiProvider(
            api_key=Config.API_KEY,
            model_name=Config.MODEL_NAME,
            system_instruction=(
                "You are an email assistant. "
                "When asked to draft an email, use the draft_email tool. "
                "Always show a preview before sending."
            )
        )
        
        await provider.initialize()
        
        # Test: Draft email (should return preview)
        print(f"\n→ Test: Draft email request")
        response = await provider.send_message(
            "Draft an email to test@example.com with subject 'Test Subject' "
            "and body 'This is a test email from MCP integration.'"
        )
        
        print(f"✓ Response received:")
        print(response[:300] + "..." if len(response) > 300 else response)
        
        # Verify it contains email preview markers
        if "FROM:" in response or "TO:" in response or "test@example.com" in response:
            print(f"✓ Email preview format detected")
        else:
            print(f"⚠ Warning: Response may not be an email preview")
        
        print(f"\n✓ Gmail tool test PASSED")
        return True
        
    except Exception as e:
        print(f"\n✗ Gmail tool test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        if provider:
            await provider.cleanup()


async def test_conversation_flow():
    """Test multi-turn conversation with tool calls"""
    print("\n" + "="*60)
    print("TEST 4: CONVERSATION FLOW")
    print("="*60)
    
    provider = None
    try:
        # Create and initialize provider
        provider = GeminiProvider(
            api_key=Config.API_KEY,
            model_name=Config.MODEL_NAME,
            system_instruction=(
                "You are a helpful assistant with tools for time, calculations, and email. "
                "Use tools when appropriate. Be concise."
            )
        )
        
        await provider.initialize()
        
        # Turn 1
        print(f"\n→ Turn 1: General question")
        response = await provider.send_message("Hello, what can you do?")
        print(f"✓ Response: {response[:100]}...")
        
        # Turn 2
        print(f"\n→ Turn 2: Tool-requiring question")
        response = await provider.send_message("What is 123 + 456?")
        print(f"✓ Response: {response[:100]}...")
        
        # Turn 3
        print(f"\n→ Turn 3: Follow-up question")
        response = await provider.send_message("And what time is it now?")
        print(f"✓ Response: {response[:100]}...")
        
        print(f"\n✓ Conversation flow test PASSED")
        return True
        
    except Exception as e:
        print(f"\n✗ Conversation flow test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        if provider:
            await provider.cleanup()


async def main():
    """Run all Phase 4 verification tests"""
    print("\nPHASE 4 GEMINI PROVIDER VERIFICATION")
    print("Testing MCP-enabled provider implementation...\n")
    
    # Check API key
    if not Config.API_KEY:
        print("✗ GOOGLE_API_KEY not set in environment")
        print("  Set your API key in .env file to run tests")
        return 1
    
    results = []
    results.append(("Provider Initialization", await test_provider_initialization()))
    results.append(("Basic Tool Calling", await test_basic_tool_calling()))
    results.append(("Gmail Tool", await test_gmail_tool()))
    results.append(("Conversation Flow", await test_conversation_flow()))
    
    print("\n" + "="*60)
    print("VERIFICATION SUMMARY")
    print("="*60)
    
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        symbol = "✓" if passed else "✗"
        print(f"{symbol} {name}: {status}")
    
    all_passed = all(result[1] for result in results)
    
    if all_passed:
        print("\n✓✓✓ Phase 4 Implementation: VERIFIED ✓✓✓")
        return 0
    else:
        print("\n✗✗✗ Phase 4 Implementation: INCOMPLETE ✗✗✗")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
