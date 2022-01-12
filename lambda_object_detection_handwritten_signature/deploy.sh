#!/usr/bin/env bash
######################################  DISCLAIMER ####################################
## YOU NEED TO HAVE INSTALLED DOCKER IN YOUR ENVIRONMENT BEFORE RUNNING THIS SCRIPT  ##
#######################################################################################

LAMBDA_PATH=$(pwd)
LAMBDA_NAME=$(basename $LAMBDA_PATH)
PARAMETERS=$LAMBDA_PATH/$LAMBDA_NAME".json"
REGION=$(jq -r '.Parameters | .pRegion' $PARAMETERS)
PROFILE=$(jq -r '.Parameters | .pProfile' $PARAMETERS)
echo "Executing with profile:" $PROFILE
echo "Executing in region:" $REGION

ACCOUNT_ID=$(jq -r '.Parameters | .pAccountID' $PARAMETERS)
APPLICATION_ID=$(jq -r '.Parameters | .pApplicationID' $PARAMETERS)
APPLICATION_NAME=$(jq -r '.Parameters | .pApplicationName' $PARAMETERS)
ENVIRONMENT=$(jq -r '.Parameters | .pEnvironment' $PARAMETERS)
PREFIX=$APPLICATION_ID"-"$APPLICATION_NAME"-"$ENVIRONMENT

CLOUDFORMATION_TMP_BUCKET=$PREFIX"-"$(jq -r '.Parameters | .pS3CloudformationTempBucket' $PARAMETERS)

echo $CLOUDFORMATION_TMP_BUCKET
bucketstatus=$(aws s3api head-bucket --bucket "${CLOUDFORMATION_TMP_BUCKET}" --region $REGION --profile $PROFILE 2>&1)
if echo "${bucketstatus}" | grep 'Not Found';
  then
     aws s3api create-bucket --bucket $CLOUDFORMATION_TMP_BUCKET --region $REGION --profile $PROFILE
     aws s3api put-public-access-block --bucket $CLOUDFORMATION_TMP_BUCKET --region $REGION --profile $PROFILE --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
     echo "cloudformation temp bucket created"
  else
     echo "cloudformation temp bucket already exists"
fi
sleep 5

##########################################################################
############ DEPLOYING ECR REPOSITORY  #########
##########################################################################

ECR_TEMPLATE=$LAMBDA_PATH/$LAMBDA_NAME"_ecr.yaml"
ECR_STACK_NAME=$PREFIX"-"$LAMBDA_NAME"-ECR-stack"
ECR_STACK_NAME=$(echo "$ECR_STACK_NAME" | sed "s/_/-/g")

echo 'Building the ecr stack '
aws cloudformation package \
    --template-file $ECR_TEMPLATE \
    --s3-bucket $CLOUDFORMATION_TMP_BUCKET \
    --output-template-file output-custom-ecr-template.yaml \
    --profile $PROFILE --debug

echo "Updating ecr Stack"
aws cloudformation deploy \
    --template-file output-custom-ecr-template.yaml \
    --s3-bucket $CLOUDFORMATION_TMP_BUCKET \
    --capabilities CAPABILITY_NAMED_IAM \
    --parameter-overrides \
    $(jq -r '.Parameters | keys[] as $k | "\($k)=\(.[$k])"' $PARAMETERS) \
    --stack-name $ECR_STACK_NAME --profile $PROFILE --region $REGION

##########################################################################
############ CREATE AND PUBLISH DOCKER IMAGE IN ECR REPOSITORY  #########
##########################################################################

#build image with dockerfile. ( execute where you have Dockerfile )
docker build -t lambda_object_detection_handwritten_signature_image .

######################## THIS SECTION IS FOR MANUAL TESTING PURPOSES ONLY ######################
#run lambda image
#docker run -d --name lambda_object_detection_handwritten_signature_container -p 9000:8080 lambda_object_detection_handwritten_signature_image

#test lambda image locally outside docker
#curl -XPOST "http://localhost:9000/2015-03-31/functions/function/invocations" -d '{"files_to_process":[{"source": "s3://nu0087001-aid-dev-s3-working-letters/fraude/carta_laboral/CartaLaboralExample.pdf","targets": [{"path": "s3://nu0087001-aid-dev-s3-working-letters/fraude/carta_laboral/CartaLaboralExample_page0.png","width": 200,"height": 200}]}]}'

# to copy test files to docker image when running. needs to put the name assigned by docker.
#docker cp code/lambda_object_detection_handwritten_signature.py lambda_object_detection_handwritten_signature_container:/var/task
################################################################################################

aws ecr get-login-password --profile $PROFILE --region $REGION | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com

######################## THIS SECTION IS FOR MANUAL TESTING PURPOSES ONLY ######################
# create repository manually ( we are creating it using cloudformation )
# aws ecr create-repository --profile bc --region us-east-1 --repository-name ecr-repository --image-scanning-configuration scanOnPush=true --image-tag-mutability MUTABLE
################################################################################################

docker tag lambda_object_detection_handwritten_signature_image:latest $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$PREFIX-ecr-repository:latest
docker push $ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/$PREFIX-ecr-repository:latest

echo "docker image published successfully ..."

##########################################################################
############ DEPLOYING LAMBDA  #########
##########################################################################

echo "Starting deploy lambda custom with ECR"

MAIN_TEMPLATE=$LAMBDA_PATH/$LAMBDA_NAME".yaml"
LAMBDA_STACK_NAME=$PREFIX"-"$LAMBDA_NAME"-Stack"
LAMBDA_STACK_NAME=$(echo "$LAMBDA_STACK_NAME" | sed "s/_/-/g")


echo 'Building the lambda stack '

aws s3 sync $LAMBDA_PATH s3://$CLOUDFORMATION_TMP_BUCKET/lambda/$LAMBDA_NAME --region $REGION --profile $PROFILE

aws cloudformation package \
    --template-file $MAIN_TEMPLATE \
    --s3-bucket $CLOUDFORMATION_TMP_BUCKET \
    --output-template-file output-custom-lambda-template.yaml \
    --profile $PROFILE --debug

echo "Updating Stack"
aws cloudformation deploy \
    --template-file output-custom-lambda-template.yaml \
    --s3-bucket $CLOUDFORMATION_TMP_BUCKET \
    --capabilities CAPABILITY_NAMED_IAM \
    --parameter-overrides \
    $(jq -r '.Parameters | keys[] as $k | "\($k)=\(.[$k])"' $PARAMETERS) \
    --stack-name $LAMBDA_STACK_NAME --profile $PROFILE --region $REGION


rm -rf output-custom-lambda-template.yaml
rm -rf output-custom-ecr-template.yaml
