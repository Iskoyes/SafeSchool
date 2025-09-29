import os, json, time, cv2, numpy as np, requests
from datetime import datetime
from insightface.app import FaceAnalysis
from dotenv import load_dotenv


SIM_THRESHOLD = 0.38         
STABLE_SEC = 2.0             
EVENT_COOLDOWN_SEC = 120     
CAM_INDEX = 0                


load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

def load_db():
    db = np.load("faces_db.npz", allow_pickle=True)
    names = list(db["names"])
    embs = db["embs"]  
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    embs = embs / np.clip(norms, 1e-9, None)
    
    return names, embs

def load_parents():

    with open("parents.json", "r", encoding="utf-8") as f:
        return json.load(f)

def notify_parents(student_id: str, text: str, frame=None):
    chat_ids = PARENTS.get(student_id, [])
    for cid in chat_ids:
        try:
            requests.get(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                params={"chat_id": cid, "text": text, "disable_notification": "true"},
                timeout=5,
            )
            if frame is not None:
                _, buf = cv2.imencode(".jpg", frame)
                requests.post(
                    f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                    data={"chat_id": cid},
                    files={"photo": ("frame.jpg", buf.tobytes(), "image/jpeg")},
                    timeout=5,
                )
        except Exception as e:
            print("Telegram error:", e)

def cosine_sim_matrix(A, b):
    return A @ b  
def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def pick_largest_face(faces):
    if not faces: return None
    areas = [(f, (f.bbox[2]-f.bbox[0])*(f.bbox[3]-f.bbox[1])) for f in faces]
    return max(areas, key=lambda x: x[1])[0]

NAMES, EMBS = load_db()
PARENTS = load_parents()

app = FaceAnalysis(providers=['CPUExecutionProvider'])
app.prepare(ctx_id=0, det_size=(640, 640))

cap = cv2.VideoCapture(CAM_INDEX)
cv2.namedWindow("Safeschool - Recognition", cv2.WINDOW_NORMAL)

stable_name = None
stable_since = None
last_event_at = {}  

print("Готово. Держите лицо в кадре 2–3 сек для срабатывания события. Выход: Q/ESC.")
while True:
    ok, frame = cap.read()
    if not ok:
        print("Камера недоступна.")
        break

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    faces = app.get(rgb)
    f = pick_largest_face(faces)

    name, sim_best = None, -1.0

    if f is not None:
        emb = f.embedding
        emb = emb / np.linalg.norm(emb)
        sims = cosine_sim_matrix(EMBS, emb)
        idx = int(np.argmax(sims))
        sim_best = float(sims[idx])
        if sim_best >= SIM_THRESHOLD:
            name = NAMES[idx]

        x1, y1, x2, y2 = f.bbox.astype(int)
        color = (0, 255, 0) if name else (0, 0, 255)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f"{name or 'unknown'} ({sim_best:.2f})"
        cv2.putText(frame, label, (x1, max(20, y1 - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    now = time.time()
    if name:
        if stable_name != name:
            stable_name = name
            stable_since = now
        else:
            held = now - (stable_since or now)
            cv2.putText(frame, f"stable: {held:.1f}s/{STABLE_SEC}s", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

            if held >= STABLE_SEC:
                last_t = last_event_at.get(name, 0)
                if now - last_t >= EVENT_COOLDOWN_SEC:
                    text = f"✅ {name} вошёл в школу в {now_str()}"
                    notify_parents(name, text, frame)
                    print(text)
                    last_event_at[name] = now
                   
                stable_name, stable_since = None, None
    else:
        stable_name, stable_since = None, None

    cv2.imshow("Safeschool - Recognition", frame)
    key = cv2.waitKey(10) & 0xFF
    if key in (ord('q'), ord('Q'), 27):
        break

cap.release()
cv2.destroyAllWindows()
