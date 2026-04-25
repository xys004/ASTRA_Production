import time
import os
import subprocess
from dotenv import load_dotenv, set_key

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def setup_api_keys():
    env_file = ".env"
    if not os.path.exists(env_file):
        open(env_file, 'a').close()
        
    load_dotenv(env_file)
    
    api_openai = os.environ.get("OPENAI_API_KEY")
    api_anthropic = os.environ.get("ANTHROPIC_API_KEY")
    api_gemini = os.environ.get("GEMINI_API_KEY")
    
    if not any([api_openai, api_anthropic, api_gemini]):
        print("\n[FIRST TIME SETUP]")
        print("It seems you don't have any API keys configured yet.")
        print("Let's set up at least one so ASTRA can operate.")
        
        gemini = input("\n1. Please paste your GEMINI API KEY (or press Enter to skip): ").strip()
        if gemini:
            set_key(env_file, "GEMINI_API_KEY", gemini)
            os.environ["GEMINI_API_KEY"] = gemini
            
        anthropic = input("2. Please paste your ANTHROPIC API KEY (or press Enter to skip): ").strip()
        if anthropic:
            set_key(env_file, "ANTHROPIC_API_KEY", anthropic)
            os.environ["ANTHROPIC_API_KEY"] = anthropic
            
        openai = input("3. Please paste your OPENAI API KEY (or press Enter to skip): ").strip()
        if openai:
            set_key(env_file, "OPENAI_API_KEY", openai)
            os.environ["OPENAI_API_KEY"] = openai

def main():
    clear_screen()
    print("="*60)
    print("   ASTRA PRODUCTION (Asynchronous API Orchestrator)")
    print("="*60)
    print("\nThis environment will execute research using official LLM API credits.")
    
    setup_api_keys()
    
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
