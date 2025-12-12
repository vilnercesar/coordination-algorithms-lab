# ==============================================================================
# FASE 0: INICIALIZAÇÃO (TERMINAL PRINCIPAL)
# ==============================================================================

# 1. Iniciar Minikube
minikube start

# 2. Configurar Docker (CRUCIAL)
eval $(minikube docker-env)

# 3. Construir Imagem
docker build -t distributed-system:v1 .

# 4. Deploy
kubectl apply -f k8s.yaml

# 5. Verificar se tudo está "Running"
kubectl get pods

# ==============================================================================
# FASE 1: PREPARAÇÃO (ABRIR NOVAS ABAS)
# ==============================================================================

# --- ABA 1 (Deixe rodando) ---
kubectl port-forward deployment/process-0 5000:5000

# --- ABA 2 (Deixe rodando) ---
kubectl port-forward deployment/process-1 5001:5000

# --- ABA 3 (Deixe rodando) ---
kubectl port-forward deployment/process-2 5002:5000

# --- ABA 4 (Visualização) ---
kubectl logs -f deployment/process-0

# --- ABA 5 (Visualização) ---
kubectl logs -f deployment/process-1

# --- ABA 6 (Visualização) ---
kubectl logs -f deployment/process-2

# ==============================================================================
# GRAVAÇÃO: COMANDOS DE CENA (RODAR NA ABA 7 - DIRETOR)
# ==============================================================================

# --- CENA 1: MULTICAST (ATRASO) ---

# Configurar atraso de 5s no P1
curl -X POST http://localhost:5001/config/delay \
     -H "Content-Type: application/json" \
     -d '{"seconds": 5}'

# Enviar mensagem (Multicast)
curl -X POST http://localhost:5000/initiate \
     -H "Content-Type: application/json" \
     -d '{"content": "Teste Multicast K8s"}'

# (Verifique os logs nas Abas 4, 5 e 6)

# --- CENA 2: MUTEX (FILA) ---

# P0 pede recurso (Sucesso imediato)
curl -X POST http://localhost:5000/mutex/request_resource

# P1 pede recurso (Vai para fila)
curl -X POST http://localhost:5001/mutex/request_resource

# P0 libera recurso (P1 deve assumir automaticamente)
curl -X POST http://localhost:5000/mutex/release_resource

# P1 libera recurso (Limpeza)
curl -X POST http://localhost:5001/mutex/release_resource

# --- CENA 3: ELEIÇÃO (BULLY) ---

# Matar o Líder (Processo 2)
kubectl scale deployment process-2 --replicas=0

# P0 tenta pedir recurso (Detecta falha e inicia eleição)
curl -X POST http://localhost:5000/mutex/request_resource

# Verificar quem é o novo líder (Deve ser o 1)
curl http://localhost:5000/health