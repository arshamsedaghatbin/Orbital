# استفاده از پایتون نسخه سبک
FROM python:3.10-slim

# تعیین پوشه کاری
WORKDIR /app

# نصب کتابخانه‌های مورد نیاز
RUN pip install ollama requests

# کپی کردن کدهای تو به داخل کانتینر
COPY . .

# اجرای برنامه (اسم فایل اصلی‌ات رو جایگزین کن)
CMD ["python", "main.py"]
