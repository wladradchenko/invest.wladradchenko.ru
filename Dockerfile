# Используем Python 3.10 как базовый образ
FROM python:3.10-slim

# Устанавливаем системные зависимости
# TA-Lib требует компиляции, поэтому нужны build tools
RUN apt-get update && apt-get install -y \
    build-essential \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем TA-Lib системную библиотеку
RUN wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz && \
    tar -xzf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib/ && \
    ./configure --prefix=/usr && \
    make && \
    make install && \
    cd .. && \
    rm -rf ta-lib ta-lib-0.4.0-src.tar.gz

# Устанавливаем Python зависимости для TA-Lib
RUN pip install --no-cache-dir numpy

# Устанавливаем TA-Lib Python wrapper
RUN pip install --no-cache-dir TA-Lib

# Создаем рабочую директорию
WORKDIR /app

# Копируем requirements.txt и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем все файлы приложения
COPY . .

# Создаем директории для базы данных и кеша (если их нет)
RUN mkdir -p cache translations/ru/LC_MESSAGES

# Компилируем переводы (если нужно)
RUN if [ -f translations/ru/LC_MESSAGES/messages.po ]; then \
    pybabel compile -d translations -l ru || true; \
    fi

# Открываем порт
EXPOSE 8080

# Переменные окружения
ENV PYTHONUNBUFFERED=1

# Команда запуска
CMD ["python", "app.py"]
