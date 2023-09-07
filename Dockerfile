# FROM python:3.9
FROM ubuntu:22.04
RUN apt update
# RUN apt install python3.9
# RUN apt install software-properties-common -y
# RUN add-apt-repository ppa:deadsnakes/ppa
# RUN apt install python3.9 -y
RUN apt install python3 python3-pip -y

# RUN apt install python3-pip -y
# RUN apt install python3.9-venv
# RUN apt install python3.9-tk
COPY . .

# sudo apt install python3.9
# RUN pip install --upgrade pip
# RUN python -m venv gplan_env
# ENV PATH="/gplan_env/bin:$PATH"
RUN pip install -r requirements.txt
EXPOSE 5000
RUN export DISPLAY=:0.0
CMD ["python", "main.py"]
