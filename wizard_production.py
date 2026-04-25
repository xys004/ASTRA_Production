import time
import os
import subprocess
import webbrowser
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
    print("   ASTRA WEB STUDIO (Local Server)")
    print("="*60)
    
    setup_api_keys()
    
    print("\nStarting ASTRA Web Studio Server...\n")
    print("Please wait, your browser will open automatically...")
    
    time.sleep(2)
    webbrowser.open("http://127.0.0.1:5050")
    
    # Run the Flask app
    subprocess.run(["python", "web/app.py"])

if __name__ == "__main__":
    main()
