@echo off
cd /d C:\Users\ggamd\Desktop\news-summarizer
echo ===== %date% %time% (%1) ===== >> run_digest.log
"C:\Users\ggamd\AppData\Local\Python\pythoncore-3.14-64\python.exe" build_digest.py %1 >> run_digest.log 2>&1
git add digest.json >> run_digest.log 2>&1
git commit -m "chore: digest update (%1)" >> run_digest.log 2>&1
git push >> run_digest.log 2>&1
