from flask import Flask, request
import main

app = Flask(__name__)

def run(url):
    return main.fetch_url(url)

@app.route('/run', methods=['GET'])
def run_endpoint():
    url = request.args.get('url')

    if not url:
        return 'Error: Please provide a URL with the "url" parameter.', 400

    # Check if the URL has a protocol, add 'http://' if missing
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    result = run(url)
    return result

if __name__ == '__main__':
    app.run(debug=True)