import sys
from avicenna.client import AvicennaClient

def main():
    print("Avicenna AI - Initializing...")
    
    try:
        client = AvicennaClient()
        print("Initialization Complete. Type 'exit' or 'quit' to stop.")
        print("-" * 50)
    except ValueError as e:
        print(f"Configuration Error: {e}")
        print("Please check your .env file.")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected Error: {e}")
        sys.exit(1)

    while True:
        try:
            user_input = input("You> ").strip()
            
            if not user_input:
                continue
                
            if user_input.lower() in ['exit', 'quit']:
                print("Goodbye!")
                break
                
            print("Avicenna> ", end="", flush=True)
            response = client.send_message(user_input)
            print(response)
            
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")

if __name__ == "__main__":
    main()
