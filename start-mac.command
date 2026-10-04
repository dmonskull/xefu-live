#!/bin/zsh
cd "${0:A:h}"
# use the first python that has everything (the Homebrew one often has no tkinter)
for py in python3 /usr/local/bin/python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3 /usr/bin/python3; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c "import tkinter, numpy, PIL" >/dev/null 2>&1; then
    exec "$py" -m xefulive "$@"
  fi
done
echo "No Python with tkinter, numpy and Pillow was found."
echo "Install Python from python.org, then run:  python3 -m pip install -r requirements.txt"
read -k 1 "?Press any key to close"
