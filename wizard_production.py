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
    print("\nEste entorno ejecutará la investigación utilizando créditos de API oficiales de LLMs.")
    
    api_openai = os.environ.get("OPENAI_API_KEY")
    api_anthropic = os.environ.get("ANTHROPIC_API_KEY")
    api_gemini = os.environ.get("GEMINI_API_KEY")
    
    print("\n[ESTADO DE LLAVES API]")
    print(f"OpenAI: {'Configurada' if api_openai else 'No detectada'}")
    print(f"Anthropic: {'Configurada' if api_anthropic else 'No detectada'}")
    print(f"Gemini: {'Configurada' if api_gemini else 'No detectada'}")
    
    if not any([api_openai, api_anthropic, api_gemini]):
        print("\nADVERTENCIA: No tienes ninguna llave configurada. El sistema operará en MODO SIMULADO.")
    
    resp = input("\n¿Iniciar el Orquestador Asíncrono de la Compañía? (s/n): ")
    if resp.lower() == 's':
        print("\nIniciando ASTRA Production...\n")
        subprocess.run(["python", "main.py"])
    else:
        print("Operación cancelada.")

if __name__ == "__main__":
    main()
