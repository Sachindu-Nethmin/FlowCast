import os
import sys
import subprocess
from pathlib import Path
from dotenv import load_dotenv

def check_env():
    print("🔍 Checking Environment Variables...")
    load_dotenv()
    required_vars = ["GROQ_API_KEY", "GROQ_VISION_MODEL", "LLM_PROVIDER"]
    all_ok = True
    for var in required_vars:
        val = os.getenv(var)
        if val:
            print(f"✅ {var} is set.")
        else:
            print(f"❌ {var} is MISSING.")
            all_ok = False
    return all_ok

def check_dependencies():
    print("\n🔍 Checking Dependencies...")
    deps = ["ffmpeg"]
    all_ok = True
    for dep in deps:
        try:
            subprocess.run([dep, "-version"], capture_output=True, check=True)
            print(f"✅ {dep} is installed.")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print(f"❌ {dep} is NOT found in PATH.")
            all_ok = False
    return all_ok

def check_wso2():
    print("\n🔍 Checking WSO2 Integrator...")
    app_path = Path.home() / "Applications/WSO2 Integrator.app"
    if app_path.exists():
        print(f"✅ WSO2 Integrator found at {app_path}")
    else:
        print(f"⚠️  WSO2 Integrator NOT found at {app_path} (Check if this is expected)")
    
    workspace_path = Path.home() / "wso2mi/workspace"
    if workspace_path.exists():
        print(f"✅ WSO2 Workspace found at {workspace_path}")
    else:
        print(f"⚠️  WSO2 Workspace NOT found at {workspace_path}")

def main():
    print("🚀 FlowCast Setup Verification\n" + "="*30)
    env_ok = check_env()
    deps_ok = check_dependencies()
    check_wso2()
    
    print("\n" + "="*30)
    if env_ok and deps_ok:
        print("🎉 Setup looks good! You are ready to run FlowCast.")
        print("\nTry running:")
        print("uv run python main.py workflows/hello_world.md")
    else:
        print("❌ Setup has issues. Please check the errors above.")

if __name__ == "__main__":
    main()
