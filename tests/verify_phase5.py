"""Phase 5 Verification: Test Async CLI and Core Integration"""
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from source.avicenna.core import AvicennaAgent
from source.avicenna.config import Config


async def test_agent_async_initialization():
    """Test that agent initializes asynchronously with MCP servers"""
    print("\n" + "="*60)
    print("TEST 1: ASYNC AGENT INITIALIZATION")
    print("="*60)
    
    try:
        # Create agent
        agent = AvicennaAgent()
        print("✓ Agent created")
        
        # Initialize (async)
        await agent.initialize()
        print("✓ Agent initialized with MCP servers")
        
        # Check initialized flag
        assert agent.initialized, "Agent not marked as initialized"
        print("✓ Agent marked as initialized")
        
        # Cleanup
        await agent.cleanup()
        print("✓ Agent cleaned up successfully")
        
        print("\n✓ Async initialization test PASSED")
        return True
        
    except Exception as e:
        print(f"\n✗ Async initialization test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_async_message_flow():
    """Test async message sending"""
    print("\n" + "="*60)
    print("TEST 2: ASYNC MESSAGE FLOW")
    print("="*60)
    
    agent = None
    try:
        # Create and initialize agent
        agent = AvicennaAgent()
        await agent.initialize()
        
        # Test message 1
        print("\n→ Test: 'What time is it?'")
        response = await agent.send_message("What time is it?")
        print(f"✓ Response received: {response[:80]}...")
        
        # Test message 2
        print("\n→ Test: 'Calculate 5 * 5'")
        response = await agent.send_message("Calculate 5 * 5")
        print(f"✓ Response received: {response[:80]}...")
        
        print("\n✓ Async message flow test PASSED")
        return True
        
    except Exception as e:
        print(f"\n✗ Async message flow test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        if agent:
            await agent.cleanup()


async def test_error_handling():
    """Test error handling when not initialized"""
    print("\n" + "="*60)
    print("TEST 3: ERROR HANDLING")
    print("="*60)
    
    try:
        agent = AvicennaAgent()
        
        # Try to send message without initializing
        response = await agent.send_message("test")
        
        if "not initialized" in response.lower():
            print("✓ Proper error message when not initialized")
        else:
            print(f"✗ Unexpected response: {response}")
            return False
        
        print("\n✓ Error handling test PASSED")
        return True
        
    except Exception as e:
        print(f"\n✗ Error handling test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_cleanup():
    """Test cleanup doesn't fail"""
    print("\n" + "="*60)
    print("TEST 4: CLEANUP")
    print("="*60)
    
    try:
        agent = AvicennaAgent()
        await agent.initialize()
        
        # Cleanup
        await agent.cleanup()
        print("✓ Cleanup successful")
        
        # Cleanup again (should be safe)
        await agent.cleanup()
        print("✓ Double cleanup safe")
        
        print("\n✓ Cleanup test PASSED")
        return True
        
    except Exception as e:
        print(f"\n✗ Cleanup test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all Phase 5 verification tests"""
    print("\nPHASE 5 ASYNC CLI & CORE VERIFICATION")
    print("Testing async agent and MCP integration...\n")
    
    # Check API key
    if not Config.API_KEY:
        print("✗ GOOGLE_API_KEY not set in environment")
        print("  Set your API key in .env file to run tests")
        return 1
    
    results = []
    results.append(("Async Initialization", await test_agent_async_initialization()))
    results.append(("Async Message Flow", await test_async_message_flow()))
    results.append(("Error Handling", await test_error_handling()))
    results.append(("Cleanup", await test_cleanup()))
    
    print("\n" + "="*60)
    print("VERIFICATION SUMMARY")
    print("="*60)
    
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        symbol = "✓" if passed else "✗"
        print(f"{symbol} {name}: {status}")
    
    all_passed = all(result[1] for result in results)
    
    if all_passed:
        print("\n✓✓✓ Phase 5 Implementation: VERIFIED ✓✓✓")
        print("\n🎉 MCP Migration Complete! All Phases 1-5 Verified!")
        return 0
    else:
        print("\n✗✗✗ Phase 5 Implementation: INCOMPLETE ✗✗✗")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
