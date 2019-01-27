import hmac
import logging
from json import dumps
from os import X_OK, access, getenv, listdir
from os.path import join
from subprocess import PIPE, Popen
from sys import stderr, exit
from traceback import print_exc


from flask import Flask, abort, request
from multiprocessing import Process

import os

logging.basicConfig(stream=stderr, level=logging.INFO)

# Collect all scripts now; we don't need to search every time
# Allow the user to override where the hooks are stored
HOOKS_DIR = getenv("WEBHOOK_HOOKS_DIR", "/app/hooks")
scripts = [join(HOOKS_DIR, f) for f in listdir(HOOKS_DIR)]
scripts = [f for f in scripts if access(f, X_OK)]
if not scripts:
    logging.error("No executable hook scripts found; did you forget to"
                  " mount something into %s or chmod +x them?", HOOKS_DIR)
    exit(1)

logging.info(dumps(scripts));

# Get application secret
webhook_secret = getenv('WEBHOOK_SECRET')
if webhook_secret is None:
    logging.error("Must define WEBHOOK_SECRET")
    exit(1)

# Get branch list that we'll listen to, defaulting to just 'master'
branch_whitelist = getenv('WEBHOOK_BRANCH_LIST', 'master').split(',')

# Our Flask application
application = Flask(__name__)

# Keep the logs of the last execution around
responses = {}

def callScript(script, branch, repository):

    os.chmod(script, 0o744)

    proc = Popen([script, branch, repository], stdout=PIPE, stderr=PIPE)

    stdout, stderr = proc.communicate()
    stdout = stdout.decode('utf-8')
    stderr = stderr.decode('utf-8')

    # Log errors if a hook failed
    if proc.returncode != 0:
        logging.error('Script: [%s]: %d\n%s', script, proc.returncode, stderr)
    else:
        logging.info('Script: [%s]: %d\nOut: %s\nErr: %s', script, proc.returncode, stdout, stderr)
        
    responses[script] = {
        'script': script,
        'args': stderr
    }

@application.route('/', methods=['POST'])
def index():
    global webhook_secret, branch_whitelist, scripts, responses

    # Get signature from the webhook request
    header_signature = request.headers.get('X-Hub-Signature')
    if header_signature is None:
        logging.info("X-Hub-Signature was missing, aborting")
        abort(403)

    # Construct an hmac, abort if it doesn't match
    sha_name, signature = header_signature.split('=')
    data = request.get_data()
    mac = hmac.new(webhook_secret.encode('utf8'), msg=data, digestmod=sha_name)
    if not hmac.compare_digest(str(mac.hexdigest()), str(signature)):
        logging.info("Signature did not match (%s and %s), aborting", str(mac.hexdigest()), str(signature))
        abort(403)
    
    # Respond to ping properly
    event = request.headers.get("X-GitHub-Event", "ping")
    if event == "ping":
        return dumps({"msg": "pong"})

    # Don't listen to anything but push
    if event != "push":
        logging.info("Not a push event, aborting")
        abort(403)

    # Try to parse out the branch from the request payload
    try:
        messageAsJson = request.get_json(force=True)
    except:
        print_exc()
        logging.info("Parsing payload failed")
        abort(400)

    try:
        branch = messageAsJson["ref"].split("/", 2)[2]
    except:
        print_exc()
        logging.info("Parsing payload failed")
        abort(400)

    # Reject branches not in our whitelist
    if branch not in branch_whitelist:
        logging.info("Branch %s not in branch_whitelist %s",
                     branch, branch_whitelist)
        abort(403)
    

    # Run scripts, saving into responses (which we clear out)
    scriptInfo = []

    for script in scripts:

        logging.info("Update received, launching {v}".format(v=script))

        repository = messageAsJson["repository"]["git_url"]

        p = Process(target=callScript, args=(script, branch, repository))
        p.start()

        scriptInfo.append({
            "script": script,
            "args": [branch, repository]
        })

    return dumps(scriptInfo)

@application.route('/logs', methods=['GET'])
def logs():
    return dumps(responses)


# Run the application if we're run as a script
if __name__ == '__main__':
    logging.info("All systems operational, beginning application loop")
    application.run(debug=False, host='0.0.0.0', port=80)
