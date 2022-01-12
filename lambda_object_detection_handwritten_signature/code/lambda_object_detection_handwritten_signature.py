
import os
import logging
from botocore.exceptions import NoCredentialsError
import boto3

from mrcnn.model import MaskRCNN
import tensorflow as tf
import warnings
import skimage.io
from PIL import Image
from ConfigModel import ConfigModel
import PIL

# PIL Configuration
PIL.Image.MAX_IMAGE_PIXELS = 933120000

# Logging Definition
logging.basicConfig()
logger = logging.getLogger(__name__)
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
logger.setLevel(getattr(logging, LOG_LEVEL))
logger.info('Loading Lambda Function {}'.format(__name__))

# Env Variables
SNS_ERROR_NAME = os.getenv('SNS_ERROR_NAME')
FILE_BUCKET = os.getenv('FILE_BUCKET')
TMP_FOLDER = '/tmp/'
MODEL_FILE = "./model.h5"
DEFAULT_CONFIDENCE_WITHOUT_SIGNATURE = "0.9"
model_initiated = False
model = None

# ARN Assembling
REGION = boto3.session.Session().region_name
try:
    ACCOUNT_ID = boto3.client('sts').get_caller_identity().get('Account')
    SNS_ERROR_ARN = "arn:aws:sns:" + str(REGION) + ":" + str(ACCOUNT_ID) + ":"+str(SNS_ERROR_NAME)
except NoCredentialsError:
    ACCOUNT_ID = None
    SNS_ERROR_ARN = None

# Boto3 clients
sns_client = boto3.client('sns', region_name='us-east-1')
s3_client = boto3.client('s3')

# avoid tensorflow warnings
warnings.filterwarnings("ignore", category=FutureWarning)
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
tf.compat.v1.logging.set_verbosity(tf.compat.v1.logging.ERROR)

    
def lambda_handler(event, context):
    """main method that orchestrates ml model call and sends a response.

    Keyword arguments:
    event -- json event with the file to process information
    context -- lambda context object, not used
    """
    logger.debug('Starting processing event: {}'.format(event))
    files_to_process = event['files_to_process']
    results = []
    for object_to_process in files_to_process:
        has_signature = False
        for object in object_to_process['targets']:
            png_image_path = object['path']
            confidence, has_signature = detect_signature(png_image_path)
            if has_signature is True:
                results.append({
                    "contains_handwritten_signature":  str(has_signature),
                    "confidence": str(confidence)
                })
                break
        if has_signature is False:
            results.append({
                "contains_handwritten_signature":  str(has_signature),
                "confidence":  str(confidence)
            })
    final_result = {"files_to_process": results}
    logger.info("result::: " + str(final_result))
    return final_result


def detect_signature(file):
    """method that process a given file name ( s3 path ),
    validates its extension , download the file and apply the ml model.

    Keyword arguments:
    file -- file name to process
    """
    key = "/".join(file.split('/')[3:])
    key_part = key.split('/')
    filename = key_part[-1]
    extension = filename.split('.')[-1]
    if extension not in ["png", "jpg"]:
        raise FormatError(
            "File type is not allowed: " + extension + ". Must be a png or jpg file")
    else:
        tmp_path = TMP_FOLDER + filename
        download_file(key, tmp_path)
        logger.info("detecting signature in document: " + key)
        return apply_model(tmp_path)


def download_file(s3_file_key, local_temp_path):
    """method that downloads a file from s3 path, and save it in a given local path

    Keyword arguments:
    s3_file_key -- s3 file to download
    local_temp_path -- local file system path to download the file, in lambda would be /tmp
    """
    logger.info('downloading file from s3:'+ str(s3_file_key))
    try:
        s3_client.download_file(FILE_BUCKET, s3_file_key, local_temp_path)
        logger.info(s3_file_key + ' downloaded')
    except Exception as msg:
        msg_exception = "Error executing lambda: " + str(msg)
        logger.info('There is an error downloading the documents: ' + str(msg))
        send_notification(SNS_ERROR_ARN,
                          "Lambda Object Detection handwritten signature s3 error",
                          msg_exception)
        raise S3Error('There is an error downloading the documents: ' + str(msg))


def apply_model(local_file_path):
    """method that converts the image to jpg if necessary, and run the tensorflow - keras model.
       based on the "rois" array, defines if the image has handwritten signature or not

    Keyword arguments:
    local_file_path -- local file to process
    """
    try:
        model = initialize_model()
        if local_file_path.endswith(".png"):
            local_file_path = convert_png_to_jpg(local_file_path)
        image = skimage.io.imread(local_file_path)
        model_result = model.detect([image], verbose=1)
        signature_result = model_result[0]
        has_signature = False
        confidence = DEFAULT_CONFIDENCE_WITHOUT_SIGNATURE
        if len(signature_result["rois"]) != 0:
            has_signature = True
            confidence = signature_result["scores"][0]
        return confidence, has_signature
    except Exception as msg:
        msg_exception = "Error executing lambda: " + str(msg)
        send_notification(SNS_ERROR_ARN,
                          "Lambda Object Detection handwritten signature model error",
                          msg_exception
                          )
        raise ApplyModelError('There is an error applying signature model to image: ' + str(msg))


def initialize_model():
    """method that initialize the MaskRCNN H5 model if neccesary
    """
    global model_initiated, model
    if not model_initiated:
        model = MaskRCNN(mode="inference", model_dir="./", config=ConfigModel())
        model.load_weights(MODEL_FILE, by_name=True)
        model_initiated = True
    return model


def convert_png_to_jpg(url):
    """method that converts the given image from png to jpg.

    Keyword arguments:
    url -- path to the png image
    """
    logger.info("convert png to jpg:" + url)
    url_without_extension = url.split(".")[0]
    url_jpg = url_without_extension + ".jpg"
    image_png = Image.open(url)
    rgb_im = image_png.convert('RGB')
    rgb_im.save(url_jpg)
    return url_jpg


def send_notification(sns_arn, subject, message):
    """method that sends a SNS notification in case of any error in the lambda.

   Keyword arguments:
   sns_arn -- arn of the SNS error topic
   subject -- subject of the message
   message -- string containing the error message
   """
    try:
        response = sns_client.publish(
            TargetArn=sns_arn,
            Subject=subject,
            Message=message
        )
        logger.info('Published the message to SNS topic. {}'.format(response))
        return response

    except Exception as ne:
        logger.error('SNS Exception: {}'.format(ne))


class FormatError(Exception):
    pass


class S3Error(Exception):
    pass


class ApplyModelError(Exception):
    pass


###############################################################################
# ####ONLY FOR TESTING PURPOSES  INVOKING PYTHON IN DOCKER MANUALLY ###########
###############################################################################
#
#class Context():
#    function_name = "test_lambda"
#
#SNS_ERROR_NAME = os.getenv('SNS_ERROR_NAME', "app001-app1-dev-sns-generic-error")
#FILE_BUCKET = os.getenv('FILE_BUCKET', "app001-app1-dev-dev-s3-working-letters")
#def test_lambda():
#    event = {
#        "files_to_process": [
#            {
#                "targets": [
#                    {
#                        "path": "s3://app001-app1-dev-s3-working-letters/human-resouces/WorkingLetterExample_pag1.png",
#                        "width": 200,
#                        "height": 200
#                    }
#                ]
#            }
#        ]
#    }
#    context = Context()
#    lambda_handler(event,context)
#
#test_lambda()
