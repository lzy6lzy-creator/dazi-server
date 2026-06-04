FROM python:3.11-slim

WORKDIR /code

# Install dependencies
COPY requirements.txt .
# 先安装 CPU 版 PyTorch（避免拉入 ~2GB 的 CUDA 版）；普通依赖走国内镜像，避免构建时长失控。
RUN pip install --no-cache-dir torch \
    --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://mirrors.aliyun.com/pypi/simple \
    --trusted-host mirrors.aliyun.com
RUN pip install --no-cache-dir --timeout 120 \
    -i https://mirrors.aliyun.com/pypi/simple \
    --trusted-host mirrors.aliyun.com \
    -r requirements.txt

# Copy app code
COPY app/ /code/app/
COPY internal_test_phones.txt /code/internal_test_phones.txt

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
