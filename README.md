# Monitoramento de RAID1 com LVM e Notificação via Telegram

Este script Python monitora a saúde de um array RAID1 configurado com LVM em um sistema Debian, verificando o status do RAID, volumes LVM e saúde dos discos (SMART), enviando alertas para um bot do Telegram quando problemas são detectados.

## Requisitos

- Debian 13 (ou outra distribuição Linux)
- Array RAID1 configurado com `mdadm`
- LVM configurado sobre o RAID
- Python 3.6+
- Pacotes necessários:
  - `mdadm` (para gerenciamento do RAID)
  - `lvm2` (para gerenciamento de volumes lógicos)
  - `smartmontools` (para verificação SMART dos discos)
  - `python3-requests` (para comunicação com a API do Telegram)

### Instalação das dependências

```bash
sudo apt update
sudo apt install mdadm lvm2 smartmontools python3-requests -y
```

## Configuração do Bot do Telegram

1. **Crie um bot no Telegram:**
   - Abra o Telegram e procure por `@BotFather`
   - Envie o comando `/newbot` e siga as instruções
   - Guarde o **token** fornecido pelo BotFather

2. **Obtenha o Chat ID:**
   - Inicie uma conversa com seu novo bot
   - Envie uma mensagem qualquer para o bot
   - Acesse `https://api.telegram.org/bot<SEU_TOKEN>/getUpdates` no navegador
   - Localize o `"chat":{"id": ...}` na resposta JSON
   - Guarde este número como seu **Chat ID**

## Configuração do Script

Edite o arquivo `raid_monitor.py` e preencha as seguintes variáveis no início do código:

```python
# Token do bot do Telegram
TELEGRAM_BOT_TOKEN = "SEU_TOKEN_DO_BOT_AQUI"

# ID do chat do Telegram onde as notificações serão enviadas
TELEGRAM_CHAT_ID = "SEU_CHAT_ID_AQUI"

# Intervalo entre verificações em segundos (padrão: 1 hora = 3600 segundos)
CHECK_INTERVAL = 3600

# Nível de log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_LEVEL = "INFO"

# Caminho para o arquivo de log
LOG_FILE = "/var/log/raid_monitor.log"

# Dispositivo RAID1 a ser monitorado (ex: /dev/md0)
RAID_DEVICE = "/dev/md0"
```

### Descrição das variáveis:

| Variável | Descrição | Exemplo |
|----------|-----------|---------|
| `TELEGRAM_BOT_TOKEN` | Token fornecido pelo BotFather | `123456789:ABCdefGHIjklMNOpqrsTUVwxyz` |
| `TELEGRAM_CHAT_ID` | ID do chat onde receberá as mensagens | `-987654321` ou `123456789` |
| `CHECK_INTERVAL` | Intervalo entre verificações (em segundos) | `3600` (1 hora) |
| `LOG_LEVEL` | Nível de detalhe dos logs | `INFO`, `DEBUG`, `ERROR` |
| `LOG_FILE` | Caminho completo do arquivo de log | `/var/log/raid_monitor.log` |
| `RAID_DEVICE` | Dispositivo RAID a ser monitorado | `/dev/md0` |

## Executando o Script

### Execução manual (teste)

```bash
python3 raid_monitor.py
```

Para executar em segundo plano durante testes:
```bash
nohup python3 raid_monitor.py &
```

### Configurar como serviço systemd (recomendado para produção)

1. Crie o arquivo de serviço:

```bash
sudo nano /etc/systemd/system/raid-monitor.service
```

2. Adicione o seguinte conteúdo:

```ini
[Unit]
Description=RAID1 LVM Monitor with Telegram Alerts
After=network.target mdmonitor.service lvm2-lvmetad.service

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 /caminho/para/raid_monitor.py
Restart=always
RestartSec=60
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Importante:** Substitua `/caminho/para/raid_monitor.py` pelo caminho real do script.

3. Recarregue o systemd e inicie o serviço:

```bash
sudo systemctl daemon-reload
sudo systemctl enable raid-monitor
sudo systemctl start raid-monitor
```

4. Verifique o status do serviço:

```bash
sudo systemctl status raid-monitor
```

5. Visualize os logs em tempo real:

```bash
sudo journalctl -u raid-monitor -f
```

## O que o script monitora

### 1. Status do RAID (mdadm)
- Estado geral do array (active, degraded, rebuilding)
- Discos com falha (faulty)
- Processo de reconstrução em andamento

### 2. Status do LVM
- Volume Groups (VGs) saudáveis
- Logical Volumes (LVs) com problemas de saúde
- Physical Volumes (PVs) associados

### 3. Saúde dos Discos (SMART)
- Status SMART de cada disco físico no array
- Detecção de falhas iminentes nos discos

## Comportamento de Alertas

- **Alertas Críticos:** Enviados imediatamente quando um problema é detectado
- **Anti-Spam:** Alertas do mesmo tipo são limitados a 1 por hora para evitar inundação de mensagens
- **Logs:** Todas as verificações e alertas são registrados no arquivo de log configurado

## Formato das Mensagens no Telegram

As mensagens incluem:
- ⚠️ Indicador visual de alerta
- Data e hora do evento
- Tipo de problema detectado (RAID, LVM ou SMART)
- Detalhes específicos do problema
- Nomes dos dispositivos afetados

## Troubleshooting

### O script não envia mensagens
1. Verifique se o token e chat ID estão corretos
2. Teste a API manualmente:
   ```bash
   curl "https://api.telegram.org/bot<SEU_TOKEN>/sendMessage?chat_id=<SEU_CHAT_ID>&text=Teste"
   ```
3. Verifique os logs em `/var/log/raid_monitor.log`

### Erro de permissão ao acessar dispositivos
Execute o script como root ou adicione o usuário ao grupo apropriado:
```bash
sudo usermod -aG disk $USER
```

### SMART não disponível para alguns discos
Alguns SSDs ou controladoras podem não suportar SMART completo. O script continuará funcionando mas reportará erro para esses discos específicos.

## Segurança

- Mantenha o token do bot em segurança
- Considere usar variáveis de ambiente para credenciais sensíveis
- Restrinja o acesso ao arquivo de log
- Execute o serviço com privilégios mínimos necessários

## Licença

Este script é fornecido "como está" sem garantias. Use por sua própria conta e risco.
