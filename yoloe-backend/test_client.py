import asyncio, json, base64
from websockets import connect

def to_data_url(path):
    with open(path, "rb") as f:
        b = base64.b64encode(f.read()).decode("ascii")
    return "data:image/jpeg;base64," + b

def save_data_url_jpeg(data_url, path):
    head, b64 = data_url.split(",", 1)
    with open(path, "wb") as f:
        f.write(base64.b64decode(b64))

async def main():
    uri = "ws://localhost:8000/ws/yoloe"

    async with connect(uri) as ws:
        # Connection
        msg = await ws.recv()
        print("Server:", msg)

        # Set Labels
        labels = {
            "type": "words",
            "request_id": "w1",
            "labels": ["person", "bottle", "dog"]
        }
        await ws.send(json.dumps(labels))
        print("words_ack:", await ws.recv())

        # Send image
        test_path = "./test_images/"
        img_name = "ahhwater"
        data_url = to_data_url(test_path + img_name + ".jpg")
        await ws.send(json.dumps({
            "type": "image", "request_id": "img1", "image_b64": data_url
        }))

        msg = await ws.recv()
        print("inference_result:", msg[:300], "...")

        resp = json.loads(msg)
        new_img_name = img_name + "_annotated.jpg"
        save_data_url_jpeg(resp["annotated_image_b64"], test_path + new_img_name)
        print("Saved " + new_img_name)
        

asyncio.run(main())