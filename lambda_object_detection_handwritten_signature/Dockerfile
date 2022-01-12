FROM public.ecr.aws/lambda/python:3.7

COPY requirements.txt  ./
COPY model/x* ./

RUN  cat x* > model.h5

RUN  pip3 install -r requirements.txt

#to avoid scan vulnerabilities
RUN  yum -y update libX11
RUN  yum -y update curl
RUN  yum -y update glibc
RUN  yum -y update java-1.8.0-openjdk
RUN  yum -y update nss
RUN  yum -y update nspr
RUN  yum -y update nss-softokn
RUN  yum -y update nss-util
RUN  yum -y update rpm
RUN  yum -y update log4j-cve-2021-44228-hotpatch

# Copy handler function (from the local app directory)
COPY  code/lambda_object_detection_handwritten_signature.py  ./
COPY  code/ConfigModel.py  ./

# Overwrite the command by providing a different command directly in the template.
CMD ["lambda_object_detection_handwritten_signature.lambda_handler"]