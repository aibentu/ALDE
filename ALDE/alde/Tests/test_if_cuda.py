import torch, platform
print("Torch:", torch.__version__)
print("CUDA avail:", torch.cuda.is_available())
print("GPU count :", torch.cuda.device_count())
if torch.cuda.is_available():
    print("Name     :", torch.cuda.get_device_name(0))
PYTHON_VERSION = platform.python_version()
print("Python  :", PYTHON_VERSION)
print("Platform:", platform.platform())