"""
"""Build script for compiling C files to shared libraries for GPLAN Space Optimization
Compiles 4 C files into shared libraries and places them in the parent directory
"""

import os
import subprocess
import sys
import shutil
import platform
from pathlib import Path

# Configuration
SOURCE_DIR = Path(__file__).parent / "Space_Optimization"
TARGET_DIR = Path(__file__).parent  # Parent folder for library placement

# C files to compile
C_FILES = [
    "bfs.c",
    "corridor_creator.c",
    "corridor.c",
    "boundary_accessible_corridors.c"
]

# Determine library extension based on platform
def get_lib_extension():
    system = platform.system()
    if system == 'Windows':
        return '.dll'
    elif system == 'Darwin':  # macOS
        return '.so'
    else:  # Linux and others
        return '.so'

LIB_EXTENSION = get_lib_extension()

# Colors for terminal output
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def print_header(text):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'=' * 80}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text.center(80)}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'=' * 80}{Colors.ENDC}\n")

def print_success(text):
    print(f"{Colors.OKGREEN}✓{Colors.ENDC} {text}")

def print_error(text):
    print(f"{Colors.FAIL}✗{Colors.ENDC} {text}")

def print_info(text):
    print(f"{Colors.OKCYAN}ℹ{Colors.ENDC} {text}")

def print_warning(text):
    print(f"{Colors.WARNING}⚠{Colors.ENDC} {text}")

def check_compiler():
    """Check if GCC compiler is available"""
    compilers = ["gcc", "x86_64-w64-mingw32-gcc", "mingw32-gcc"]
    
    for compiler in compilers:
        try:
            result = subprocess.run(
                [compiler, "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                print_success(f"Found compiler: {compiler}")
                print_info(f"Version: {result.stdout.split(chr(10))[0]}")
                return compiler
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    
    print_error("No GCC compiler found!")
    print_info("Please install MinGW-w64 or GCC for Windows")
    print_info("Download from: https://www.mingw-w64.org/downloads/")
    return None

def compile_dll(compiler, source_file, source_dir, target_dir):
    """Compile a single C file to shared library"""
    source_path = source_dir / source_file
    lib_name = source_file.replace(".c", LIB_EXTENSION)
    lib_path = target_dir / lib_name
    
    if not source_path.exists():
        print_error(f"Source file not found: {source_path}")
        return False
    
    print_info(f"Compiling {source_file} → {lib_name}")
    
    # Compilation command
    # -shared: Create shared library
    # -o: Output file
    # -O2: Optimization level 2
    # -Wall: Enable all warnings
    # -fPIC: Position Independent Code (required for shared libraries on Linux/macOS)
    cmd = [
        compiler,
        "-shared",
        "-fPIC",
        "-o", str(lib_path),
        str(source_path),
        "-O2",
        "-Wall",
        f"-I{source_dir}"
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(source_dir),
            timeout=30
        )
        
        if result.returncode == 0:
            if lib_path.exists():
                file_size = lib_path.stat().st_size
                print_success(f"Created {lib_name} ({file_size:,} bytes)")
                
                # Also copy to Space_Optimization folder for local use
                local_lib = source_dir / lib_name
                shutil.copy2(lib_path, local_lib)
                print_info(f"Copied to Space_Optimization/{lib_name}")
                
                return True
            else:
                print_error(f"Library not created: {lib_name}")
                return False
        else:
            print_error(f"Compilation failed for {source_file}")
            if result.stderr:
                print(f"{Colors.FAIL}Error output:{Colors.ENDC}")
                print(result.stderr)
            return False
            
    except subprocess.TimeoutExpired:
        print_error(f"Compilation timeout for {source_file}")
        return False
    except Exception as e:
        print_error(f"Exception during compilation: {e}")
        return False

def verify_headers(source_dir):
    """Verify that all required header files exist"""
    print_info("Verifying header files...")
    
    headers = [f.replace(".c", ".h") for f in C_FILES]
    missing = []
    
    for header in headers:
        header_path = source_dir / header
        if header_path.exists():
            print_success(f"Found {header}")
        else:
            print_warning(f"Missing {header}")
            missing.append(header)
    
    return len(missing) == 0

def main():
    print_header("GPLAN C Library Build Script")
    
    print_info(f"Source directory: {SOURCE_DIR}")
    print_info(f"Target directory: {TARGET_DIR}")
    print_info(f"Files to compile: {len(C_FILES)}")
    
    # Verify source directory exists
    if not SOURCE_DIR.exists():
        print_error(f"Source directory not found: {SOURCE_DIR}")
        return 1
    
    # Verify header files
    if not verify_headers(SOURCE_DIR):
        print_warning("Some header files are missing, but continuing...")
    
    # Check for compiler
    print("\n" + "─" * 80)
    compiler = check_compiler()
    if not compiler:
        return 1
    
    # Compile each C file
    print("\n" + "─" * 80)
    print_header(f"Compiling C Files to Shared Libraries ({LIB_EXTENSION})")
    
    success_count = 0
    failed_files = []
    
    for i, c_file in enumerate(C_FILES, 1):
        print(f"\n[{i}/{len(C_FILES)}] Processing {c_file}")
        print("─" * 80)
        
        if compile_dll(compiler, c_file, SOURCE_DIR, TARGET_DIR):
            success_count += 1
        else:
            failed_files.append(c_file)
    
    # Summary
    print("\n" + "=" * 80)
    print_header("Build Summary")
    
    print(f"Total files:    {len(C_FILES)}")
    print(f"{Colors.OKGREEN}Successful:     {success_count}{Colors.ENDC}")
    print(f"{Colors.FAIL}Failed:         {len(failed_files)}{Colors.ENDC}")
    
    if failed_files:
        print(f"\n{Colors.FAIL}Failed files:{Colors.ENDC}")
        for f in failed_files:
            print(f"  • {f}")
    
    # List generated libraries
    print("\n" + "─" * 80)
    print_info(f"Generated library files in parent directory ({LIB_EXTENSION}):")
    
    for c_file in C_FILES:
        lib_name = c_file.replace(".c", LIB_EXTENSION)
        lib_path = TARGET_DIR / lib_name
        if lib_path.exists():
            file_size = lib_path.stat().st_size
            print(f"  ✓ {lib_name} ({file_size:,} bytes)")
        else:
            print(f"  ✗ {lib_name} (not found)")
    
    print("\n" + "=" * 80)
    
    if success_count == len(C_FILES):
        print_success("All libraries compiled successfully! 🎉")
        return 0
    elif success_count > 0:
        print_warning(f"Partial success: {success_count}/{len(C_FILES)} libraries compiled")
        return 1
    else:
        print_error("Build failed - no DLLs created")
        return 1

if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print(f"\n\n{Colors.WARNING}Build interrupted by user{Colors.ENDC}")
        sys.exit(130)
    except Exception as e:
        print(f"\n{Colors.FAIL}Unexpected error: {e}{Colors.ENDC}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
