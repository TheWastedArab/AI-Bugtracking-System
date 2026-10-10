"""Explicit operator command; the running API never downloads weights."""
from huggingface_hub import snapshot_download

if __name__ == '__main__':
    path = snapshot_download('sentence-transformers/all-MiniLM-L6-v2', local_dir='artifacts/all-MiniLM-L6-v2',
                             allow_patterns=['*.json', '*.safetensors', '*.txt', '1_Pooling/*'])
    print(path)
