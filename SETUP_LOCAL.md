# 🚀 Setup do Backend Local

## Problema Identificado

O erro `No module named uvicorn` indica que as dependências não estão instaladas.

## Solução: Configurar Ambiente Python

### Opção 1: Criar Virtual Environment (Recomendado)

```bash
# Na pasta backend
cd backend

# 1. Criar venv
python3 -m venv venv

# 2. Ativar venv
source venv/bin/activate

# 3. Instalar dependências
pip install -r requirements.txt

# 4. Rodar uvicorn
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

### Opção 2: Instalar Globalmente (Não Recomendado)

```bash
# Instalar uvicorn globalmente
pip3 install uvicorn[standard] fastapi

# Rodar
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

## Configuração do VSCode/Cursor

O arquivo `.vscode/launch.json` já foi atualizado com a configuração correta:

```json
{
  "name": "Python Debugger: FastAPI",
  "type": "debugpy",
  "request": "launch",
  "module": "uvicorn",
  "args": [
    "src.main:app",
    "--reload",
    "--host",
    "0.0.0.0",
    "--port",
    "8000"
  ],
  "cwd": "${workspaceFolder}/backend",
  "envFile": "${workspaceFolder}/deploy/.env"
}
```

### Para usar o debugger:

1. **Criar venv primeiro** (se ainda não tiver):
   ```bash
   cd backend
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Selecionar o interpretador Python do venv no VSCode:**
   - Pressione `Cmd+Shift+P` (Mac) ou `Ctrl+Shift+P` (Windows/Linux)
   - Digite: "Python: Select Interpreter"
   - Escolha: `./backend/venv/bin/python`

3. **Rodar o debugger:**
   - Vá em "Run and Debug" (F5)
   - Selecione "Python Debugger: FastAPI"
   - Clique em "Start Debugging"

## Variáveis de Ambiente

O `.env` está em `deploy/.env`. O launch.json já está configurado para carregar automaticamente.

Se precisar carregar manualmente:

```bash
# Na pasta backend
export $(cat ../deploy/.env | grep -v '^#' | xargs)
```

## Verificar se está funcionando

Após iniciar, acesse:
- **Health Check:** http://localhost:8000/health
- **API Docs:** http://localhost:8000/docs

## Troubleshooting

### Erro: "No module named uvicorn"
- **Solução:** Instale as dependências: `pip install -r requirements.txt`

### Erro: "ModuleNotFoundError: No module named 'src'"
- **Solução:** Certifique-se de estar na pasta `backend` ou configure `cwd` corretamente

### Erro: "DATABASE_URL not found"
- **Solução:** Verifique se o arquivo `deploy/.env` existe e tem as variáveis corretas

