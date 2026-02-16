FROM python:3.11

# Install system dependencies including GCC for compiling C libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc build-essential python3-tk tk \
    libx11-6 libxext6 libxrender1 libxtst6 libxi6 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY . .

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install -r newrequirements.txt

# Compile C libraries to .so files for Linux
# Remove any existing .dll or .so files to ensure clean build
RUN rm -f *.dll *.so Space_Optimization/*.dll Space_Optimization/*.so || true
RUN python build_dlls.py || ( \
    cd Space_Optimization && \
    gcc -shared -fPIC -o ../bfs.so bfs.c -O2 -Wall && \
    gcc -shared -fPIC -o ../corridor_creator.so corridor_creator.c -O2 -Wall && \
    gcc -shared -fPIC -o ../corridor.so corridor.c -O2 -Wall && \
    gcc -shared -fPIC -o ../boundary_accessible_corridors.so boundary_accessible_corridors.c -O2 -Wall && \
    echo "Successfully compiled all shared libraries" \
)

EXPOSE 5000
CMD ["python", "main.py"]
