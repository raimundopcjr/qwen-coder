# Monitor de RAID1 com LVM para Telegram

Script Python para monitoramento de RAID1 implementado via **LVM** (LVM Mirror/RAID1) em sistemas Debian/Ubuntu, com notificações via Telegram.

## ⚠️ Importante

Este script é específico para **RAID1 implementado via LVM**, NÃO usa `mdadm`. No LVM, o RAID1 pode ser criado de duas formas:

- **Tipo "raid1"** (mais moderno, usa dm-raid)
- **Tipo "mirror"** (legado, mas ainda funcional)

Para verificar se seu sistema usa LVM RAID1:
```bash
# Lista Logical Volumes com tipo de segmento
lvs -o name,seg_type --select seg_type=raid1
lvs -o name,seg_type --select seg_type=mirror

# Ou lista todos os LVs com detalhes
lvs -a -o +devices
```

## 📋 Requisitos

### Pacotes necessários

```bash
sudo apt update
sudo apt install python3 python3-pip lvm2 smartmontools -y
pip3 install requests
```

### Permissões

O script precisa de acesso root para executar comandos LVM e SMART:

```bash
# Execute como root ou com sudo
sudo python3 raid_monitor_lvm.py
```

## 🔧 Configuração do Telegram

### 1. Criar um Bot no Telegram

1. Abra o Telegram e busque por `@BotFather`
2. Envie o comando `/newbot`
3. Siga as instruções:
   - Dê um nome ao bot (ex: `Monitor RAID`)
   - Escolha um username (ex: `raid_monitor_bot`)
4. O BotFather retornará um **token** no formato: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`
5. **Guarde este token!** Ele será usado na variável `TELEGRAM_BOT_TOKEN`

### 2. Obter o Chat ID

Existem várias formas de obter seu Chat ID:

#### Método 1 - Via navegador (mais fácil):
1. Inicie uma conversa com seu bot no Telegram (envie `/start`)
2. Acesse no navegador: `https://api.telegram.org/bot<SEU_TOKEN>/getUpdates`
3. Procure no JSON retornado o campo `"chat":{"id":123456789,...}`
4. Este número é seu `TELEGRAM_CHAT_ID`

#### Método 2 - Usando curl:
```bash
# Substitua SEU_TOKEN pelo token do bot
curl https://api.telegram.org/botSEU_TOKEN/getUpdates
```

#### Método 3 - Bot dedicado:
1. Busque por `@userinfobot` no Telegram
2. Inicie uma conversa
3. Ele retornará seu Chat ID automaticamente

### 3. Adicionar bot a um grupo (opcional)

Se quiser receber alertas em um grupo:
1. Adicione o bot como membro do grupo
2. Torne-o administrador (opcional, mas recomendado)
3. Envie uma mensagem no grupo
4. Use o método 1 ou 2 acima, mas o Chat ID será negativo (ex: `-123456789`)

## ⚙️ Configuração do Script

Edite o arquivo `raid_monitor_lvm.py` e preencha as variáveis abaixo:

```python
# Token do bot do Telegram (obtido via @BotFather)
TELEGRAM_BOT_TOKEN = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"

# ID do chat ou usuário que receberá as notificações
TELEGRAM_CHAT_ID = "123456789"

# Intervalo entre verificações (em segundos). 3600 = 1 hora
CHECK_INTERVAL = 3600

# Nível de log: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_LEVEL = "INFO"

# Arquivo de log
LOG_FILE = "/var/log/raid_monitor.log"

# Nome do Volume Group (VG) que contém o LV espelhado
# Use 'vgs' no terminal para listar os VGs disponíveis
VOLUME_GROUP = "vg_raid"

# Nome do Logical Volume (LV) espelhado (opcional)
# Deixe vazio ("") para verificar todos os LVs do VG
# Use 'lvs -o name,seg_type --select seg_type=raid1' para identificar
LOGICAL_VOLUME = ""  # Ex: "lv_root" ou "" para todos
```

### Tabela de Variáveis

| Variável | Descrição | Exemplo | Obrigatória |
|----------|-----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Token do bot | `"123456:ABC..."` | Sim |
| `TELEGRAM_CHAT_ID` | ID do destinatário | `"123456789"` | Sim |
| `CHECK_INTERVAL` | Intervalo em segundos | `3600` (1h) | Não* |
| `LOG_LEVEL` | Nível de detalhe do log | `"INFO"` | Não |
| `LOG_FILE` | Caminho do arquivo de log | `"/var/log/raid_monitor.log"` | Não |
| `VOLUME_GROUP` | Nome do VG do RAID | `"vg_raid"` | Sim |
| `LOGICAL_VOLUME` | Nome do LV (opcional) | `""` ou `"lv_root"` | Não |

\* *Padrão: 3600 segundos (1 hora)*

## 🚀 Execução

### Teste inicial

```bash
# Teste manual (como root)
sudo python3 raid_monitor_lvm.py
```

O script enviará uma mensagem de teste ao Telegram assim que iniciar.

### Executar em background

```bash
# Usando nohup
sudo nohup python3 raid_monitor_lvm.py > /dev/null 2>&1 &

# Ou usando screen/tmux
sudo screen -S raid_monitor
python3 raid_monitor_lvm.py
# Ctrl+A, D para desanexar
```

### Como serviço systemd (recomendado)

Crie o arquivo `/etc/systemd/system/raid-monitor.service`:

```ini
[Unit]
Description=RAID1 LVM Monitor with Telegram Alerts
After=network.target local-fs.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 /caminho/para/raid_monitor_lvm.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Ative e inicie o serviço:

```bash
# Recarrega systemd
sudo systemctl daemon-reload

# Habilita na inicialização
sudo systemctl enable raid-monitor.service

# Inicia o serviço
sudo systemctl start raid-monitor.service

# Verifica status
sudo systemctl status raid-monitor.service

# Ver logs
sudo journalctl -u raid-monitor.service -f
```

## 📊 O que é monitorado

### 1. Status do RAID LVM
- Tipo de segmento (raid1 ou mirror)
- Percentual de sincronização
- Estado de saúde (ativo, parcial, inválido, etc.)
- Dispositivos físicos associados

### 2. Volume Groups (VG)
- Status geral do VG
- Estado parcial (quando um PV está faltando)
- Espaço utilizado e livre

### 3. Physical Volumes (PV)
- Lista de discos no VG
- Verifica se há pelo menos 2 PVs (necessário para RAID1)
- Tamanho e uso de cada PV

### 4. Saúde SMART dos Discos
- Status SMART de cada disco físico
- Detecção de falhas iminentes
- Alertas críticos para discos com problemas

## 🚨 Tipos de Alerta

### Críticos (enviados com cooldown de 1 hora)
- 🚨 RAID LVM degradado ou inválido
- 🚨 Volume Group em estado parcial
- 🚨 Falha iminente de disco (SMART)
- 💀 Disco reportou falha no SMART

### Avisos (enviados imediatamente)
- ⚠️ RAID em sincronização
- ⚠️ Menos de 2 PVs encontrados
- ⚠️ Erros ao verificar componentes

### Mensagens de OK (não enviadas por padrão)
- ✅ Sistema saudável
- ✅ RAID sincronizado
- ✅ Todos os discos OK

## 📝 Logs

Os logs são salvos em `/var/log/raid_monitor.log` (configurável).

Exemplo de saída:
```
2025-01-15 10:30:00,000 - INFO - ============================================================
2025-01-15 10:30:00,000 - INFO - Iniciando monitoramento do RAID1 LVM
2025-01-15 10:30:00,000 - INFO - Volume Group: vg_raid
2025-01-15 10:30:00,000 - INFO - Intervalo: 3600 segundos
2025-01-15 10:30:00,000 - INFO - ============================================================
2025-01-15 10:30:01,000 - INFO - ----------------------------------------
2025-01-15 10:30:01,000 - INFO - Verificação iniciada: 2025-01-15 10:30:01
2025-01-15 10:30:02,000 - INFO - Status RAID: ACTIVE
2025-01-15 10:30:02,000 - INFO - Saúde geral: OK
2025-01-15 10:30:02,000 - INFO - Sistema saudável. Nenhum alerta necessário.
2025-01-15 10:30:02,000 - INFO - Próxima verificação em 3600 segundos
2025-01-15 10:30:02,000 - INFO - ----------------------------------------
```

## 🔍 Troubleshooting

### "Comando LVM não encontrado"
Instale o LVM2:
```bash
sudo apt install lvm2
```

### "smartctl não instalado"
Instale o smartmontools:
```bash
sudo apt install smartmontools
```

### "Falha ao enviar mensagem"
Verifique:
1. Token do bot está correto
2. Chat ID está correto
3. Bot foi iniciado (envie `/start` para ele)
4. Firewall não está bloqueando conexões HTTPS

### "Nenhum LV RAID1/mirror encontrado"
Verifique se seu LV foi criado como RAID1:
```bash
# Mostra todos os LVs com tipo de segmento
lvs -o name,seg_type

# Se não for raid1 ou mirror, o script não funcionará
# Para criar um LV RAID1:
# lvcreate --type raid1 -m 1 -L 100G -n lv_name vg_name
```

### Erro de permissão
Execute como root:
```bash
sudo python3 raid_monitor_lvm.py
```

## 🔐 Dicas de Segurança

1. **Proteja o token do bot**: Não compartilhe publicamente
2. **Restrinja permissões do bot**: No @BotFather, use `/setcommands` para limitar ações
3. **Use grupos privados**: Para alertas, prefira grupos restritos
4. **Monitore os logs**: Configure logrotate para `/var/log/raid_monitor.log`

Exemplo de logrotate (`/etc/logrotate.d/raid-monitor`):
```
/var/log/raid_monitor.log {
    weekly
    rotate 4
    compress
    delaycompress
    missingok
    notifempty
    create 640 root adm
}
```

## 📞 Suporte

Para mais informações sobre LVM RAID1:
- [Documentação oficial do LVM](https://man7.org/linux/man-pages/man8/lvm.8.html)
- [Wiki do Arch sobre LVM](https://wiki.archlinux.org/title/LVM)

Para API do Telegram:
- [Documentação da API Bot](https://core.telegram.org/bots/api)

## 📄 Licença

Script livre para uso e modificação.
