# 📡 Laboratório de Algoritmos de Coordenação Distribuída

Este projeto é uma implementação prática de algoritmos clássicos de sistemas distribuídos, desenvolvido em **Python (FastAPI)** e orquestrado via **Kubernetes (Minikube)**. O sistema simula um ambiente de processos independentes que precisam coordenar ações, trocar mensagens e recuperar-se de falhas de forma autônoma.

## 📋 Funcionalidades Implementadas

O projeto unifica três mecanismos de coordenação no mesmo código:

* **Multicast com Ordenação Total (Relógios de Lamport):** Garante que mensagens enviadas por diferentes processos sejam entregues na mesma ordem lógica em todas as réplicas, utilizando filas de prioridade e confirmações (ACKs).
* **Exclusão Mútua Centralizada:** Gerencia o acesso a um recurso crítico compartilhado utilizando um Coordenador central e filas de espera.
* **Eleição de Líder (Algoritmo do Valentão/Bully):** Detecta a falha do coordenador e elege automaticamente um novo líder (o processo com maior ID) para restaurar a consistência do sistema.

> **Nota:** O sistema também possui funcionalidades de *Chaos Engineering* para simular atrasos de rede e testar a robustez dos algoritmos.

---

## 🔌 Principais Endpoints

| Método | Endpoint | Descrição |
| :--- | :--- | :--- |
| `POST` | `/initiate` | Envia uma mensagem em Multicast para o grupo (**Q1**). |
| `POST` | `/mutex/request_resource` | Solicita acesso à seção crítica ao líder atual (**Q2**). |
| `POST` | `/mutex/release_resource` | Libera a seção crítica, notificando o líder (**Q2**). |
| `POST` | `/election/start` | **Gatilho Manual:** Força o início de um processo de eleição de líder (**Q3**). |
| `POST` | `/election/message` | **Interno:** Recebe mensagens do protocolo de eleição (ELECTION, OK, COORDINATOR). |
| `POST` | `/config/delay` | Configura um atraso artificial no próximo ACK para simular lentidão (Teste). |
| `GET` | `/health` | Retorna o ID do processo, o Relógio de Lamport atual e o ID do Líder reconhecido. |

---

## 🛠️ Pré-requisitos

Para executar este laboratório, você precisará de:

* [Docker](https://www.docker.com/) (Instalado e rodando)
* [Minikube](https://minikube.sigs.k8s.io/docs/start/) (Para simular o cluster Kubernetes localmente)
* `kubectl` (Ferramenta de linha de comando do Kubernetes)
* **Opcional:** `curl` ou um cliente HTTP (Postman/Insomnia) para testes.

---

## 🚀 Roteiro de Instalação e Teste

Siga os passos abaixo para clonar, configurar e validar o sistema.

### 1. Instalação e Build

Primeiro, clone o repositório e inicie o ambiente:

```bash
# 1. Clone o projeto
git clone https://github.com/vilnercesar/coordination-algorithms-lab.git
cd coordination-algorithms-lab

# 2. Inicie o Minikube
minikube start

# 3. Conecte o terminal ao Docker do Minikube (CRUCIAL)
# Isso permite que o cluster "enxergue" a imagem que vamos criar
eval $(minikube docker-env)

# 4. Construa a imagem Docker
docker build -t distributed-system:v1 .

# 5. Implante os serviços no Kubernetes
kubectl apply -f k8s.yaml

# 6. Aguarde até que todos os pods estejam com status 'Running'
kubectl get pods
```

### 2. Configuração dos Terminais

Para visualizar os logs e interagir com o sistema, abra **4 terminais** (ou abas) diferentes:

* **Terminal 1 (Túnel P0):**
    ```bash
    kubectl port-forward deployment/process-0 5000:5000
    ```
* **Terminal 2 (Túnel P1):**
    ```bash
    kubectl port-forward deployment/process-1 5001:5000
    ```
* **Terminal 3 (Túnel P2):**
    ```bash
    kubectl port-forward deployment/process-2 5002:5000
    ```
* **Terminal 4 (Comandos):** Use este terminal para enviar as requisições `curl`.

> **Dica:** Para ver os logs em tempo real, você pode usar `kubectl logs -f deployment/process-X` em abas adicionais.

---

## 🧪 Cenários de Teste

Execute os comandos abaixo no **Terminal 4**.

### Cena 1: Multicast com Atraso (Ordenação Total)
*Simula um processo lento. O sistema deve esperar o processo lento responder antes de entregar a mensagem a todos.*

```bash
# Configura atraso de 5s no Processo 1
curl -X POST http://localhost:5001/config/delay -H "Content-Type: application/json" -d '{"seconds": 5}'

# Envia mensagem via Processo 0
curl -X POST http://localhost:5000/initiate -H "Content-Type: application/json" -d '{"content": "Teste Q1"}'
```
**Resultado Esperado:** Os logs devem mostrar o recebimento imediato, uma pausa de 5s, e depois a mensagem `DELIVERED` aparecendo simultaneamente em todos os nós.

### Cena 2: Exclusão Mútua (Concorrência)
*O Líder (P2) gerencia a fila. P0 pega o recurso, P1 tenta pegar e deve esperar.*

```bash
# P0 pede o recurso (Sucesso imediato)
curl -X POST http://localhost:5000/mutex/request_resource

# P1 pede o recurso (Deve ficar esperando/bloqueado)
curl -X POST http://localhost:5001/mutex/request_resource

# P0 libera o recurso (P1 deve receber acesso automaticamente agora)
curl -X POST http://localhost:5000/mutex/release_resource

# P1 libera para limpar
curl -X POST http://localhost:5001/mutex/release_resource
```

### Cena 3: Eleição de Líder (Recuperação de Falha)
*Simula a morte do Líder atual (P2). O sistema deve eleger o P1 (próximo maior ID).*

```bash
# 1. "Matar" o Líder (Processo 2)
kubectl scale deployment process-2 --replicas=0

# 2. P0 tenta usar o sistema (Gatilho da falha)
# O código detectará o erro de conexão e iniciará a eleição automaticamente
curl -X POST http://localhost:5000/mutex/request_resource
```

**Resultado Esperado:** P0 detecta timeout do líder, inicia eleição. P1 responde, ganha a eleição e se anuncia como novo líder.

```bash
# 3. Verificar quem é o novo líder
curl http://localhost:5000/health
# Deve retornar: "leader": 1
```

---

## 🛑 Encerrando

Para parar e limpar o ambiente:

```bash
minikube delete
```
