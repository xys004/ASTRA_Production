import time
import os
import subprocess

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def main():
    clear_screen()
    print("="*60)
    print("   ASTRA PRODUCTION (Asynchronous API Orchestrator)")
    print("="*60)
    print("\nThis environment will execute research using official LLM API credits.")
    
    api_openai = os.environ.get("OPENAI_API_KEY")
    api_anthropic = os.environ.get("ANTHROPIC_API_KEY")
    api_gemini = os.environ.get("GEMINI_API_KEY")
    
    print("\n[API KEYS STATUS]")
    print(f"OpenAI: {'Configured' if api_openai else 'Not detected'}")
    print(f"Anthropic: {'Configured' if api_anthropic else 'Not detected'}")
    print(f"Gemini: {'Configured' if api_gemini else 'Not detected'}")
    
    if not any([api_openai, api_anthropic, api_gemini]):
        print("\nWARNING: No API keys configured. The system will operate in SIMULATED MODE.")
    
    resp = input("\nStart the Company Asynchronous Orchestrator? (y/n): ")
    if resp.lower() == 'y':
        print("\nStarting ASTRA Production...\n")
        subprocess.run(["python", "main.py"])
    else:
        print("Operation cancelled.")

if __name__ == "__main__":
    main()
