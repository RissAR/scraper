# Базовий легкозважний образ Python 3.12
FROM python:3.12-slim

# Налаштування змінних середовища Python:
# PYTHONDONTWRITEBYTECODE=1: запобігає створенню файлів .pyc
# PYTHONUNBUFFERED=1: забезпечує негайне виведення логів у stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Встановлення необхідних системних бібліотек для роботи lxml та скрейпінгу
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libxml2-dev \
    libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

# Робоча директорія застосунку
WORKDIR /app

# Окреме копіювання requirements.txt для ефективного кешування шарів Docker
COPY requirements.txt .

# Встановлення Python-залежностей без збереження локального кешу pip
RUN pip install --no-cache-dir -r requirements.txt

# Копіювання вихідного коду проєкту
COPY . .

# Створення директорії для персистентних даних (БД SQLite та експорт Excel)
RUN mkdir -p /app/data

# Запуск Telegram-бота
CMD ["python", "bot.py"]
