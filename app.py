import os
import asyncio
import httpx
import random
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager

RELEASED = "RELEASED"
WANTED = "WANTED"
HELD = "HELD"


class Message(BaseModel):
    id: str
    timestamp: int
    sender_id: int
    content: str

class Ack(BaseModel):
    message_id: str
    sender_id: int

class MutexRequest(BaseModel):
    sender_id: int

class InitiateRequest(BaseModel):
    content: str = "Ping"

class DelayConfig(BaseModel):
    seconds: int

class ElectionMsg(BaseModel):
    type: str       # "ELECTION", "OK", "COORDINATOR"
    sender_id: int


PROCESS_ID = int(os.getenv("PROCESS_ID", "0"))
TOTAL_PROCESSES = int(os.getenv("TOTAL_PROCESSES", "3"))

PEERS = {}
for i in range(TOTAL_PROCESSES):
    PEERS[i] = os.getenv(f"PEER_{i}", f"http://localhost:500{i}")

# --- ESTADO DA APLICAÇÃO ---
state = {
    # Q1: Multicast
    "lamport_clock": random.randint(0, 10),
    "priority_queue": [],
    "ack_counts": {},
    "delay_next_ack": 0,
    
    # Q2: Mutex Centralizado
    "mutex_state": RELEASED, 
    "coord_queue": [],
    "coord_locked": False,
    
    # Q3: Eleição (Líder Dinâmico)
    "coordinator_id": TOTAL_PROCESSES - 1, 
    "election_active": False
}

http_client = httpx.AsyncClient(timeout=2.0)

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await http_client.aclose()

app = FastAPI(lifespan=lifespan)

# --- FUNÇÕES AUXILIARES ---

def sort_queue():
    state["priority_queue"].sort(key=lambda m: (m.timestamp, m.sender_id))

async def multicast(endpoint: str, payload: Dict[str, Any]):
    for peer_id, url in PEERS.items():
        asyncio.create_task(send_request(url, endpoint, payload))

async def send_request(url: str, endpoint: str, payload: Dict[str, Any]):
    try:
        await http_client.post(f"{url}{endpoint}", json=payload)
        return True
    except Exception as e:
        print(f"[Rede] Falha ao conectar em {url}: {e}")
        return False

# (Q2) Auxiliar Coordenador
async def send_grant(target_id: int):
    url = PEERS[target_id]
    print(f"[Líder] Concedendo acesso ao Processo {target_id}")
    # O sender_id no grant deve ser o meu ID atual (o líder)
    await send_request(url, "/mutex/grant", {"sender_id": PROCESS_ID})

# (Q3) Lógica do Valentão
async def start_election():
    """Inicia o processo de eleição."""
    state["election_active"] = True
    print(f"[Eleição] Iniciando eleição (Eu sou {PROCESS_ID})...")
    
    higher_processes = [pid for pid in PEERS if pid > PROCESS_ID]
    
    if not higher_processes:
        await declare_victory()
        return

    # Envia 'ELECTION' para todos os maiores
    any_ok_received = False
    for pid in higher_processes:
        print(f"[Eleição] Desafiando Processo {pid}...")
        success = await send_request(PEERS[pid], "/election/message", 
                                     {"type": "ELECTION", "sender_id": PROCESS_ID})
        if success:
            any_ok_received = True
    
    # Se ninguém maior respondeu (timeout ou erro), eu ganhei
    if not any_ok_received:
        print("[Eleição] Ninguém maior respondeu. Eu sou o novo Líder!")
        await declare_victory()
    else:
        print("[Eleição] Alguém maior respondeu. Aguardando novo líder...")
        # (Na prática, deveríamos esperar um tempo e verificar se chegou msg COORDINATOR,
        # mas para simplificar, paramos aqui e esperamos o maior assumir).

async def declare_victory():
    """Anuncia para todos que sou o novo líder."""
    state["coordinator_id"] = PROCESS_ID
    state["election_active"] = False
    state["coord_locked"] = False # Reseta estado do recurso ao assumir
    state["coord_queue"] = []
    
    print(f"*** EU SOU O NOVO LÍDER (Processo {PROCESS_ID}) ***")
    
    payload = {"type": "COORDINATOR", "sender_id": PROCESS_ID}
    await multicast("/election/message", payload)

# ==========================================
#  Q3: ENDPOINTS DE ELEIÇÃO
# ==========================================

@app.post("/election/start")
async def trigger_election():
    """Gatilho manual para iniciar eleição."""
    asyncio.create_task(start_election())
    return {"status": "election_started"}

@app.post("/election/message")
async def receive_election_msg(msg: ElectionMsg):
    sender = msg.sender_id
    
    if msg.type == "ELECTION":
        print(f"[Eleição] Recebi desafio do Processo {sender}.")
        if sender < PROCESS_ID:
            if not state["election_active"]:
                asyncio.create_task(start_election())
        return {"status": "OK"} # Isso conta como resposta "ALIVE"
        
    elif msg.type == "COORDINATOR":
        state["coordinator_id"] = sender
        state["election_active"] = False
        print(f"[Eleição] Novo Líder reconhecido: Processo {sender}")
        return {"status": "acknowledged"}
        
    return {"status": "ignored"}

# ==========================================
#  Q2: MUTEX CENTRALIZADO (ATUALIZADO)
# ==========================================

@app.post("/mutex/request_resource")
async def request_resource():
    state["mutex_state"] = WANTED
    leader = state["coordinator_id"]
    print(f"[Cliente] Pedindo recurso ao Líder atual: {leader}")
    
    leader_url = PEERS[leader]
    payload = {"sender_id": PROCESS_ID}
    
    # Tenta falar com o líder
    success = await send_request(leader_url, "/mutex/receive_request", payload)
    
    if not success:
        print(f"[Erro] O Líder {leader} não respondeu! Iniciando ELEIÇÃO.")
        asyncio.create_task(start_election())
        return {"status": "leader_dead", "action": "election_started"}
    
    return {"status": "request_sent", "state": WANTED}

@app.post("/mutex/receive_request")
async def receive_mutex_request(req: MutexRequest):
    if PROCESS_ID != state["coordinator_id"]:
        return {"status": "ignored", "reason": "Não sou líder"}

    sender = req.sender_id
    print(f"[Líder] Recebi pedido de {sender}")

    if not state["coord_locked"]:
        state["coord_locked"] = True
        await send_grant(sender)
    else:
        print(f"[Líder] Ocupado. Enfileirando {sender}")
        state["coord_queue"].append(sender)

    return {"status": "received"}

@app.post("/mutex/grant")
async def receive_grant(req: MutexRequest):
    if state["mutex_state"] == WANTED:
        state["mutex_state"] = HELD
        print(f"*** [Cliente] ACESSO PERMITIDO pelo Líder {req.sender_id}! ***")
    return {"status": "granted"}

@app.post("/mutex/release_resource")
async def release_resource():
    if state["mutex_state"] != HELD:
        return {"status": "error"}

    print(f"[Cliente] Liberando recurso.")
    state["mutex_state"] = RELEASED
    
    leader = state["coordinator_id"]
    asyncio.create_task(send_request(PEERS[leader], "/mutex/receive_release", {"sender_id": PROCESS_ID}))
    return {"status": "released"}

@app.post("/mutex/receive_release")
async def receive_release(req: MutexRequest):
    if PROCESS_ID != state["coordinator_id"]: return

    print(f"[Líder] Recurso liberado por {req.sender_id}.")
    if state["coord_queue"]:
        next_id = state["coord_queue"].pop(0)
        await send_grant(next_id)
    else:
        print("[Líder] Recurso livre.")
        state["coord_locked"] = False
    return {"status": "ok"}

# ==========================================
#  Q1: MULTICAST (INALTERADO)
# ==========================================

def check_delivery():
    queue = state["priority_queue"]
    ack_counts = state["ack_counts"]
    while queue:
        head = queue[0]
        if ack_counts.get(head.id, 0) >= TOTAL_PROCESSES:
            print(f"*** Q1 ENTREGUE: '{head.content}' (Origem: {head.sender_id})")
            queue.pop(0)
            if head.id in ack_counts: del ack_counts[head.id]
        else: break

@app.post("/initiate")
async def initiate(req: InitiateRequest):
    print(f"[Q1] 🚀 ENVIANDO mensagem em multicast (Sou o Processo {PROCESS_ID})")
    state["lamport_clock"] += 1
    ts = state["lamport_clock"]
    msg = {"id": f"{PROCESS_ID}-{ts}", "timestamp": ts, "sender_id": PROCESS_ID, "content": req.content}
    await multicast("/receive_message", msg)
    return {"status": "ok"}

@app.post("/receive_message")
async def recv_msg(msg: Message):
    state["lamport_clock"] = max(state["lamport_clock"], msg.timestamp) + 1
    state["priority_queue"].append(msg)
    sort_queue()
    if state["delay_next_ack"] > 0:
        await asyncio.sleep(state["delay_next_ack"])
        state["delay_next_ack"] = 0
    await multicast("/receive_ack", {"message_id": msg.id, "sender_id": PROCESS_ID})
    return {"status": "ok"}

@app.post("/receive_ack")
async def recv_ack(ack: Ack):
    msg_id = ack.message_id
    sender = ack.sender_id
    print(f"[ACK] Recebido confirmação do Processo {sender} para a msg {msg_id}")
    state["ack_counts"][ack.message_id] = state["ack_counts"].get(ack.message_id, 0) + 1
    check_delivery()
    return {"status": "ok"}

@app.post("/config/delay")
async def set_delay(c: DelayConfig):
    state["delay_next_ack"] = c.seconds
    return {"status": "ok"}

@app.get("/health")
async def health():
    return {
        "id": PROCESS_ID, 
        "leader": state["coordinator_id"],
        "mutex": state["mutex_state"]
    }

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=5000)