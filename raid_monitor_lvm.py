#!/usr/bin/env python3
"""
Script de monitoramento de RAID1 com LVM (LVM Mirror/RAID1) e notificação via Telegram.
Executa verificações de saúde do RAID a cada hora e envia alertas em caso de problemas.

ESTE SCRIPT É ESPECÍFICO PARA RAID1 IMPLEMENTADO VIA LVM - NÃO USA MDADM!
No LVM, o RAID1 pode ser criado usando:
- Tipo "raid1" (mais moderno, usa dm-raid)
- Tipo "mirror" (legado, mas ainda funcional)

Variáveis de configuração devem ser preenchidas abaixo.
"""

import subprocess
import time
import logging
from datetime import datetime
import requests

# ==================== CONFIGURAÇÕES ====================
# Token do bot do Telegram (obtido via @BotFather)
TELEGRAM_BOT_TOKEN = "SEU_BOT_TOKEN_AQUI"

# ID do chat ou usuário que receberá as notificações
# Para obter: envie uma mensagem ao bot e acesse https://api.telegram.org/bot<token>/getUpdates
TELEGRAM_CHAT_ID = "SEU_CHAT_ID_AQUI"

# Intervalo entre verificações (em segundos). 3600 = 1 hora
CHECK_INTERVAL = 3600

# Nível de log: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_LEVEL = "INFO"

# Arquivo de log
LOG_FILE = "/var/log/raid_monitor.log"

# Nome do Volume Group (VG) que contém o LV espelhado
# Use 'vgs' no terminal para listar os VGs disponíveis
VOLUME_GROUP = "vg_raid"

# Nome do Logical Volume (LV) espelhado (opcional, deixe vazio para verificar todos)
# Use 'lvs -o name,seg_type --select seg_type=raid1' para identificar LVs RAID1
# Use 'lvs -o name,seg_type --select seg_type=mirror' para identificar LVs mirror
LOGICAL_VOLUME = ""  # Ex: "lv_root" ou deixe "" para verificar todos

# ==================== VARIÁVEIS INTERNAS ====================
ALERT_COOLDOWN = 3600  # Tempo mínimo entre alertas críticos (em segundos)

# =======================================================

# Configuração de logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def send_telegram_message(message: str) -> bool:
    """Envia uma mensagem para o Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info("Mensagem enviada com sucesso ao Telegram.")
            return True
        else:
            logger.error(f"Falha ao enviar mensagem: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Erro ao conectar com Telegram: {e}")
        return False


def get_lvm_raid_status() -> dict:
    """
    Obtém o status do RAID1 implementado via LVM.
    Verifica LVs do tipo 'raid1' ou 'mirror'.
    """
    status = {
        "vg_name": VOLUME_GROUP,
        "status": "unknown",
        "sync_percent": None,
        "devices": [],
        "details": [],
        "is_healthy": True
    }

    try:
        # Lista todos os LVs com informações detalhadas
        result = subprocess.run(
            ["lvs", "-o", "lv_name,vg_name,lv_attr,sync_percent,copy_percent,devices", 
             "--noheadings", "--units", "g"],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            status["status"] = "error"
            status["details"].append(f"Erro ao executar lvs: {result.stderr}")
            status["is_healthy"] = False
            return status

        found_raid = False
        
        for line in result.stdout.strip().split('\n'):
            if not line.strip():
                continue
            
            parts = line.split()
            if len(parts) < 3:
                continue
            
            lv_name = parts[0]
            vg_name = parts[1]
            lv_attr = parts[2] if len(parts) > 2 else ""
            sync_pct = parts[3] if len(parts) > 3 else "0"
            copy_pct = parts[4] if len(parts) > 4 else "0"
            
            # Filtra pelo VG configurado
            if VOLUME_GROUP and vg_name != VOLUME_GROUP:
                continue
            
            # Se tiver LV específico, filtra por ele
            if LOGICAL_VOLUME and lv_name != LOGICAL_VOLUME:
                continue
            
            # Verifica se é RAID1 ou Mirror pelo primeiro caractere do lv_attr
            # r = raid, m = mirror
            vol_type = lv_attr[0] if len(lv_attr) > 0 else ''
            is_raid = vol_type in ['r', 'm']
            
            if is_raid:
                found_raid = True
                
                # Interpreta o tipo
                raid_type = "RAID1" if vol_type == 'r' else "MIRROR"
                
                # Verifica estado de sincronização
                sync_val = sync_pct.replace('%', '').replace('g', '')
                try:
                    sync_float = float(sync_val) if sync_val else 0
                except ValueError:
                    sync_float = 0
                
                if sync_float < 100:
                    status["sync_percent"] = sync_float
                    status["details"].append(f"⚠️ {raid_type} {lv_name} sincronizando: {sync_float}%")
                else:
                    status["sync_percent"] = 100.0
                    status["details"].append(f"✅ {raid_type} {lv_name} sincronizado")
                
                # Verifica health state (posição 5 do lv_attr)
                # p = partial, I = invalid, s = snapshot, m = refreshing
                if len(lv_attr) >= 5:
                    health_char = lv_attr[4]
                    if health_char == 'p':
                        status["status"] = "DEGRADED"
                        status["is_healthy"] = False
                        status["details"].append(f"🚨 LV {lv_name} em estado PARCIAL!")
                    elif health_char == 'I':
                        status["status"] = "INVALID"
                        status["is_healthy"] = False
                        status["details"].append(f"🚨 LV {lv_name} INVÁLIDO!")
                    elif health_char == 'm':
                        status["status"] = "REFRESHING"
                        status["details"].append(f"🔄 LV {lv_name} em refresh")
                    else:
                        status["status"] = "ACTIVE"
                        status["details"].append(f"✅ LV {lv_name} ativo e saudável")
                else:
                    status["status"] = "ACTIVE"
                
                # Extrai dispositivos físicos
                if len(parts) > 5:
                    devices_info = ' '.join(parts[5:])
                    status["devices"].append({
                        "lv": lv_name,
                        "vg": vg_name,
                        "type": raid_type,
                        "devices": devices_info
                    })

        if not found_raid:
            if VOLUME_GROUP:
                status["status"] = "WARNING"
                status["details"].append(f"⚠️ Nenhum LV RAID1/mirror encontrado no VG '{VOLUME_GROUP}'")
                status["details"].append("   Verifique se o LV foi criado corretamente como RAID1")
            else:
                status["status"] = "WARNING"
                status["details"].append("⚠️ Nenhum LV RAID1/mirror encontrado no sistema")

        return status

    except subprocess.TimeoutExpired:
        status["status"] = "TIMEOUT"
        status["is_healthy"] = False
        status["details"].append("Tempo esgotado ao verificar LVM")
        return status
    except FileNotFoundError as e:
        status["status"] = "ERROR"
        status["is_healthy"] = False
        status["details"].append(f"Comando LVM não encontrado: {e}")
        return status
    except Exception as e:
        status["status"] = "ERROR"
        status["is_healthy"] = False
        status["details"].append(f"Erro inesperado: {str(e)}")
        return status


def check_vg_health() -> dict:
    """Verifica a saúde dos Volume Groups."""
    status = {"vg_status": "ok", "details": []}

    try:
        result = subprocess.run(
            ["vgs", "--noheadings", "-o", "vg_name,vg_status,vg_size,vg_free,pv_count"],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    vg_name = parts[0]
                    vg_stat = parts[1]
                    
                    if VOLUME_GROUP and vg_name != VOLUME_GROUP:
                        continue
                    
                    status["details"].append(f"VG: {vg_name}, Status: {vg_stat}")
                    
                    if "partial" in vg_stat.lower():
                        status["vg_status"] = "DEGRADED"
                        status["details"].append(f"🚨 VG {vg_name} em estado PARCIAL!")
        else:
            status["vg_status"] = "ERROR"
            status["details"].append(f"Erro ao verificar VGs: {result.stderr}")

        return status
    except Exception as e:
        status["vg_status"] = "ERROR"
        status["details"].append(f"Erro: {str(e)}")
        return status


def check_pv_health() -> dict:
    """Verifica a saúde dos Physical Volumes (discos)."""
    status = {"pv_status": "ok", "pvs": [], "details": []}

    try:
        result = subprocess.run(
            ["pvs", "--noheadings", "-o", "pv_name,vg_name,pv_size,pv_used,pv_free"],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    pv_name = parts[0]
                    vg_name = parts[1]
                    
                    if VOLUME_GROUP and vg_name != VOLUME_GROUP:
                        continue
                    
                    status["pvs"].append(pv_name)
                    status["details"].append(f"PV: {pv_name} no VG {vg_name}")
        else:
            status["pv_status"] = "WARNING"
            status["details"].append(f"Aviso ao verificar PVs: {result.stderr}")

        # Verifica se temos pelo menos 2 PVs para RAID1
        if len(status["pvs"]) < 2:
            status["details"].append(f"⚠️ Apenas {len(status['pvs'])} PV(s) encontrado(s). RAID1 precisa de 2+")
        
        return status
    except Exception as e:
        status["pv_status"] = "ERROR"
        status["details"].append(f"Erro: {str(e)}")
        return status


def check_disk_smart(disk_list: list) -> dict:
    """Verifica a saúde SMART dos discos físicos."""
    health_status = {"overall": "ok", "disks": []}

    disks_to_check = disk_list if disk_list else ["/dev/sda", "/dev/sdb"]

    for disk in disks_to_check:
        try:
            result = subprocess.run(
                ["smartctl", "-H", disk],
                capture_output=True,
                text=True,
                timeout=30
            )

            disk_info = {"device": disk, "health": "unknown", "details": []}

            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if "SMART overall-health" in line or "SMART Health Status" in line:
                        if "PASSED" in line:
                            disk_info["health"] = "PASSED"
                        elif "FAILED" in line:
                            disk_info["health"] = "FAILED"
                            health_status["overall"] = "CRITICAL"
                        disk_info["details"].append(line.strip())
                
                if disk_info["health"] == "unknown":
                    disk_info["health"] = "PASSED"  # Assume OK se não houver falha explícita
            else:
                disk_info["health"] = "ERROR"
                disk_info["details"].append(f"Erro: {result.stderr.strip()}")

            health_status["disks"].append(disk_info)

        except FileNotFoundError:
            health_status["overall"] = "WARNING"
            health_status["disks"].append({
                "device": disk,
                "health": "UNKNOWN",
                "details": ["smartctl não instalado"]
            })
        except Exception as e:
            health_status["disks"].append({
                "device": disk,
                "health": "ERROR",
                "details": [str(e)]
            })

    return health_status


def analyze_health(raid_status: dict, vg_status: dict, pv_status: dict, smart_status: dict) -> tuple:
    """Analisa a saúde geral e retorna (is_healthy, message)."""
    issues = []
    warnings = []

    # Analisa RAID LVM
    if not raid_status.get("is_healthy", True):
        issues.append(f"🚨 PROBLEMA NO RAID LVM: {raid_status.get('status', 'DESCONHECIDO')}")
    
    for detail in raid_status.get("details", []):
        if "🚨" in detail or "DEGRADED" in detail or "PARCIAL" in detail:
            issues.append(detail)
        elif "⚠️" in detail or "sincronizando" in detail.lower():
            warnings.append(detail)

    # Analisa VG
    if vg_status.get("vg_status") == "DEGRADED":
        issues.append("🚨 Volume Group DEGRADADO!")
    elif vg_status.get("vg_status") == "ERROR":
        issues.append("🚨 Erro no Volume Group!")

    # Analisa PV
    pv_count = len(pv_status.get("pvs", []))
    if pv_count < 2:
        warnings.append(f"⚠️ Apenas {pv_count} PV(s) encontrado(s). RAID1 requer mínimo 2 discos.")

    # Analisa SMART
    if smart_status.get("overall") == "CRITICAL":
        issues.append("🚨 FALHA IMINENTE DE DISCO detectada pelo SMART!")
    
    for disk in smart_status.get("disks", []):
        if disk.get("health") == "FAILED":
            issues.append(f"💀 Disco {disk['device']} reportou FALHA no SMART!")
        elif disk.get("health") == "ERROR":
            warnings.append(f"⚠️ Não foi possível verificar SMART de {disk['device']}")

    # Constrói mensagem
    timestamp = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    
    if issues:
        message = "🚨 *ALERTA CRÍTICO - RAID1 LVM*\n\n"
        message += "\n".join(issues)
        if warnings:
            message += "\n\n⚠️ *Avisos adicionais:*\n" + "\n".join(warnings)
        message += f"\n\n📅 Data: {timestamp}"
        message += f"\n🖥️ VG: {VOLUME_GROUP}"
        if LOGICAL_VOLUME:
            message += f" | LV: {LOGICAL_VOLUME}"
        return False, message

    elif warnings:
        message = "⚠️ *ALERTA - Atenção Necessária*\n\n"
        message += "\n".join(warnings)
        message += f"\n\n📅 Data: {timestamp}"
        message += f"\n🖥️ VG: {VOLUME_GROUP}"
        return True, message

    else:
        message = "✅ *RAID1 LVM Saudável*\n\n"
        message += f"Estado: {raid_status.get('status', 'desconhecido')}\n"
        
        sync = raid_status.get("sync_percent")
        if sync is not None:
            message += f"Sincronização: {sync}%\n"
        
        message += f"VG: {vg_status.get('vg_status', '?')}\n"
        message += f"PVs: {pv_count} discos\n"
        
        smart_overall = smart_status.get("overall", "?")
        message += f"SMART: {smart_overall}\n"
        message += f"\n📅 Data: {timestamp}"
        message += f"\n🖥️ VG: {VOLUME_GROUP}"
        if LOGICAL_VOLUME:
            message += f" | LV: {LOGICAL_VOLUME}"
        
        return True, message


def main():
    """Função principal do monitor."""
    logger.info("=" * 60)
    logger.info("Iniciando monitoramento do RAID1 LVM")
    logger.info(f"Volume Group: {VOLUME_GROUP}")
    if LOGICAL_VOLUME:
        logger.info(f"Logical Volume: {LOGICAL_VOLUME}")
    logger.info(f"Intervalo: {CHECK_INTERVAL} segundos")
    logger.info("=" * 60)

    # Valida configurações
    if TELEGRAM_BOT_TOKEN == "SEU_BOT_TOKEN_AQUI" or TELEGRAM_CHAT_ID == "SEU_CHAT_ID_AQUI":
        logger.error("Configure TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID antes de executar!")
        print("\n❌ ERRO: Você precisa configurar as variáveis TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID")
        print("   Edite este arquivo e substitua os valores placeholder.\n")
        return

    # Envia mensagem de teste
    test_message = "🤖 *Teste do Monitor RAID LVM*\n\n"
    test_message += "O serviço de monitoramento foi iniciado.\n"
    test_message += f"VG: {VOLUME_GROUP}\n"
    if LOGICAL_VOLUME:
        test_message += f"LV: {LOGICAL_VOLUME}\n"
    test_message += f"Intervalo: {CHECK_INTERVAL/60:.0f} minutos\n"
    send_telegram_message(test_message)

    last_alert_time = None

    while True:
        try:
            logger.info("-" * 40)
            logger.info(f"Verificação iniciada: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

            # Coleta informações
            raid_status = get_lvm_raid_status()
            vg_status = check_vg_health()
            pv_status = check_pv_health()
            
            # Extrai lista de discos para verificar SMART
            disk_list = pv_status.get("pvs", [])
            smart_status = check_disk_smart(disk_list)

            # Analisa saúde geral
            is_healthy, message = analyze_health(raid_status, vg_status, pv_status, smart_status)

            # Log do status
            logger.info(f"Status RAID: {raid_status.get('status', 'unknown')}")
            logger.info(f"Saúde geral: {'OK' if is_healthy else 'PROBLEMA DETECTADO'}")

            # Envia alerta se necessário
            if not is_healthy:
                current_time = time.time()

                # Evita spam de alertas críticos
                if last_alert_time is None or (current_time - last_alert_time) > ALERT_COOLDOWN:
                    logger.warning("Enviando alerta crítico ao Telegram...")
                    if send_telegram_message(message):
                        last_alert_time = current_time
                        logger.info("Alerta enviado com sucesso.")
                    else:
                        logger.error("Falha ao enviar alerta.")
                else:
                    remaining = ALERT_COOLDOWN - (current_time - last_alert_time)
                    logger.info(f"Alerta suprimido (cooldown). Próximo em {remaining:.0f}s")

            # Para avisos não críticos, envia sem cooldown
            elif "⚠️" in message and "Atenção" in message:
                logger.info("Enviando aviso não crítico...")
                send_telegram_message(message)
            else:
                logger.info("Sistema saudável. Nenhum alerta necessário.")

            logger.info(f"Próxima verificação em {CHECK_INTERVAL} segundos")
            logger.info("-" * 40)

            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            logger.info("Monitoramento interrompido pelo usuário.")
            send_telegram_message("⏹️ *Monitoramento Parado*\n\nO script foi interrompido manualmente.")
            break
        except Exception as e:
            logger.error(f"Erro no loop principal: {e}", exc_info=True)
            error_msg = f"🚨 *ERRO NO MONITOR*\n\nErro inesperado:\n{str(e)}\n\nVerifique os logs."
            send_telegram_message(error_msg)
            time.sleep(60)


if __name__ == "__main__":
    main()
