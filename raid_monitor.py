#!/usr/bin/env python3
"""
Script de monitoramento de RAID1 com LVM e notificação via Telegram.
Executa verificações de saúde do RAID a cada hora e envia alertas em caso de problemas.

Variáveis de configuração devem ser preenchidas abaixo.
"""

import subprocess
import time
import logging
from datetime import datetime
import requests

# ==================== CONFIGURAÇÕES ====================
# ID do bot do Telegram (obtido via @BotFather)
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

# Dispositivo RAID para monitorar (ajuste conforme seu sistema)
# Exemplos: /dev/md0, /dev/mapper/vg_name-lv_name
RAID_DEVICE = "/dev/md0"

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


def get_raid_status() -> dict:
    """Obtém o status do RAID usando mdadm."""
    status = {
        "device": RAID_DEVICE,
        "status": "unknown",
        "active_devices": 0,
        "total_devices": 0,
        "sync_status": "unknown",
        "details": []
    }
    
    try:
        # Executa mdadm --detail para obter informações detalhadas
        result = subprocess.run(
            ["mdadm", "--detail", RAID_DEVICE],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            status["status"] = "error"
            status["details"].append(f"Erro ao executar mdadm: {result.stderr}")
            return status
        
        output_lines = result.stdout.strip().split('\n')
        
        for line in output_lines:
            line = line.strip()
            
            # Estado do array
            if line.startswith("State :"):
                state_value = line.split(":")[1].strip()
                status["status"] = state_value
                status["details"].append(line)
            
            # Dispositivos ativos
            elif "Active Devices" in line:
                try:
                    status["active_devices"] = int(line.split(":")[1].strip())
                except ValueError:
                    pass
            
            # Total de dispositivos
            elif "Raid Devices" in line or "Total Devices" in line:
                try:
                    status["total_devices"] = int(line.split(":")[1].strip())
                except ValueError:
                    pass
            
            # Status de sincronização
            elif "recovery" in line.lower() or "resync" in line.lower():
                status["sync_status"] = line
                status["details"].append(line)
        
        # Verifica se há falhas nos dispositivos
        for line in output_lines:
            if "faulty" in line.lower() or "removed" in line.lower():
                status["details"].append(f"ALERTA: {line}")
        
        return status
    
    except subprocess.TimeoutExpired:
        status["status"] = "timeout"
        status["details"].append("Tempo esgotado ao verificar RAID")
        return status
    except FileNotFoundError:
        status["status"] = "error"
        status["details"].append("Comando mdadm não encontrado. Instale com: apt install mdadm")
        return status
    except Exception as e:
        status["status"] = "error"
        status["details"].append(f"Erro inesperado: {str(e)}")
        return status


def check_lvm_status() -> dict:
    """Verifica o status do LVM associado ao RAID."""
    status = {
        "vg_status": "unknown",
        "lv_status": "unknown",
        "details": []
    }
    
    try:
        # Verifica Volume Groups
        result_vg = subprocess.run(
            ["vgs", "--noheadings", "-o", "vg_name,vg_status"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result_vg.returncode == 0:
            status["vg_status"] = "ok"
            status["details"].append("VGs:")
            for line in result_vg.stdout.strip().split('\n'):
                if line.strip():
                    status["details"].append(f"  {line.strip()}")
        else:
            status["vg_status"] = "warning"
            status["details"].append(f"Aviso ao verificar VGs: {result_vg.stderr}")
        
        # Verifica Logical Volumes
        result_lv = subprocess.run(
            ["lvs", "--noheadings", "-o", "lv_name,vg_name,lv_status"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result_lv.returncode == 0:
            status["lv_status"] = "ok"
            status["details"].append("LVs:")
            for line in result_lv.stdout.strip().split('\n'):
                if line.strip():
                    status["details"].append(f"  {line.strip()}")
        else:
            status["lv_status"] = "warning"
            status["details"].append(f"Aviso ao verificar LVs: {result_lv.stderr}")
        
        return status
    
    except Exception as e:
        status["vg_status"] = "error"
        status["lv_status"] = "error"
        status["details"].append(f"Erro ao verificar LVM: {str(e)}")
        return status


def check_disk_health(device: str = None) -> dict:
    """Verifica a saúde dos discos usando smartctl."""
    health_status = {
        "disks": [],
        "overall": "ok"
    }
    
    # Lista de discos possíveis (ajuste conforme necessário)
    disks_to_check = ["/dev/sda", "/dev/sdb", "/dev/sdc", "/dev/sdd"]
    
    if device:
        # Tenta extrair o disco base do dispositivo RAID
        try:
            result = subprocess.run(
                ["mdadm", "--detail", RAID_DEVICE],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if "/dev/sd" in line and "active sync" in line.lower():
                        disk = line.split()[2] if len(line.split()) > 2 else None
                        if disk and disk not in disks_to_check:
                            disks_to_check.append(disk)
        except:
            pass
    
    for disk in disks_to_check:
        try:
            result = subprocess.run(
                ["smartctl", "-H", disk],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            disk_info = {
                "device": disk,
                "health": "unknown",
                "details": []
            }
            
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if "SMART overall-health" in line or "SMART Health Status" in line:
                        if "PASSED" in line:
                            disk_info["health"] = "passed"
                        elif "FAILED" in line:
                            disk_info["health"] = "failed"
                            health_status["overall"] = "critical"
                        disk_info["details"].append(line.strip())
            else:
                disk_info["health"] = "error"
                disk_info["details"].append(f"Erro: {result.stderr.strip()}")
            
            health_status["disks"].append(disk_info)
        
        except FileNotFoundError:
            health_status["overall"] = "warning"
            health_status["disks"].append({
                "device": disk,
                "health": "smartctl não instalado",
                "details": ["Instale com: apt install smartmontools"]
            })
        except Exception as e:
            health_status["disks"].append({
                "device": disk,
                "health": "error",
                "details": [str(e)]
            })
    
    return health_status


def analyze_raid_health(raid_status: dict, lvm_status: dict, disk_health: dict) -> tuple:
    """Analisa a saúde geral do RAID e retorna (is_healthy, message)."""
    issues = []
    warnings = []
    
    # Analisa status do RAID
    raid_state = raid_status.get("status", "").lower()
    
    if "degraded" in raid_state:
        issues.append("🚨 RAID DEGRADADO! Um ou mais discos falharam.")
    elif "inactive" in raid_state:
        issues.append("🚨 RAID INATIVO! O array está parado.")
    elif "error" in raid_state:
        issues.append("🚨 ERRO no estado do RAID!")
    elif "clean" in raid_state or "active" in raid_state:
        pass  # Estado normal
    else:
        warnings.append(f"⚠️ Estado do RAID desconhecido: {raid_state}")
    
    # Verifica número de dispositivos
    active = raid_status.get("active_devices", 0)
    total = raid_status.get("total_devices", 2)  # Espera-se 2 para RAID1
    
    if active < total:
        issues.append(f"⚠️ Apenas {active}/{total} dispositivos ativos no RAID.")
    
    # Verifica sincronização
    sync_status = raid_status.get("sync_status", "")
    if "recovery" in sync_status.lower() or "resync" in sync_status.lower():
        warnings.append(f"🔄 RAID em sincronização: {sync_status}")
    
    # Verifica detalhes problemáticos
    for detail in raid_status.get("details", []):
        if "faulty" in detail.lower() or "removed" in detail.lower():
            issues.append(f"💥 Disco problemático detectado: {detail}")
    
    # Analisa LVM
    if lvm_status.get("vg_status") == "error":
        issues.append("🚨 Erro nos Volume Groups do LVM!")
    elif lvm_status.get("vg_status") == "warning":
        warnings.append("⚠️ Aviso nos Volume Groups do LVM.")
    
    if lvm_status.get("lv_status") == "error":
        issues.append("🚨 Erro nos Logical Volumes do LVM!")
    elif lvm_status.get("lv_status") == "warning":
        warnings.append("⚠️ Aviso nos Logical Volumes do LVM.")
    
    # Analisa saúde dos discos
    if disk_health.get("overall") == "critical":
        issues.append("🚨 FALHA IMINENTE DE DISCO detectada pelo SMART!")
    elif disk_health.get("overall") == "warning":
        warnings.append("⚠️ Não foi possível verificar a saúde de todos os discos.")
    
    for disk in disk_health.get("disks", []):
        if disk.get("health") == "failed":
            issues.append(f"💀 Disco {disk['device']} reportou falha no SMART!")
    
    # Constrói mensagem
    if issues:
        message = "🚨 *ALERTA CRÍTICO - RAID1*\n\n"
        message += "\n".join(issues)
        if warnings:
            message += "\n\n⚠️ *Avisos adicionais:*\n" + "\n".join(warnings)
        message += f"\n\n📅 Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        message += f"\n🖥️ Dispositivo: {RAID_DEVICE}"
        return False, message
    
    elif warnings:
        message = "⚠️ *ALERTA - Atenção Necessária*\n\n"
        message += "\n".join(warnings)
        message += f"\n\n📅 Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        message += f"\n🖥️ Dispositivo: {RAID_DEVICE}"
        return True, message  # Considera saudável mas com avisos
    
    else:
        message = "✅ *RAID1 Saudável*\n\n"
        message += f"Estado: {raid_status.get('status', 'desconhecido')}\n"
        message += f"Dispositivos: {raid_status.get('active_devices', 0)}/{raid_status.get('total_devices', 0)} ativos\n"
        message += f"LVM: VG={lvm_status.get('vg_status', '?')} LV={lvm_status.get('lv_status', '?')}\n"
        message += f"SMART: {disk_health.get('overall', '?').upper()}\n"
        message += f"\n📅 Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        return True, message


def main():
    """Função principal do monitor."""
    logger.info("=" * 60)
    logger.info("Iniciando monitoramento do RAID1")
    logger.info(f"Dispositivo: {RAID_DEVICE}")
    logger.info(f"Intervalo: {CHECK_INTERVAL} segundos")
    logger.info(f"Telegram Chat ID: {TELEGRAM_CHAT_ID}")
    logger.info("=" * 60)
    
    # Testa conexão com Telegram
    if TELEGRAM_BOT_TOKEN == "SEU_BOT_TOKEN_AQUI" or TELEGRAM_CHAT_ID == "SEU_CHAT_ID_AQUI":
        logger.error("Configure TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID antes de executar!")
        print("\n❌ ERRO: Você precisa configurar as variáveis TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID")
        print("   Edite este arquivo e substitua os valores placeholder.\n")
        return
    
    test_message = "🤖 *Teste do Monitor RAID*\n\nO serviço de monitoramento foi iniciado.\n"
    test_message += f"Dispositivo: {RAID_DEVICE}\n"
    test_message += f"Intervalo: {CHECK_INTERVAL/60:.0f} minutos\n"
    send_telegram_message(test_message)
    
    last_alert_time = None
    alert_cooldown = 3600  # Não enviar mais de um alerta crítico por hora
    
    while True:
        try:
            logger.info("-" * 40)
            logger.info(f"Iniciando verificação às {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Coleta informações
            raid_status = get_raid_status()
            lvm_status = check_lvm_status()
            disk_health = check_disk_health()
            
            # Analisa saúde
            is_healthy, message = analyze_raid_health(raid_status, lvm_status, disk_health)
            
            # Log do status
            logger.info(f"Status do RAID: {raid_status.get('status', 'unknown')}")
            logger.info(f"Saúde geral: {'OK' if is_healthy else 'PROBLEMA DETECTADO'}")
            
            # Envia alerta se necessário
            if not is_healthy:
                current_time = time.time()
                
                # Evita spam de alertas
                if last_alert_time is None or (current_time - last_alert_time) > alert_cooldown:
                    logger.warning("Enviando alerta crítico ao Telegram...")
                    if send_telegram_message(message):
                        last_alert_time = current_time
                        logger.info("Alerta enviado com sucesso.")
                    else:
                        logger.error("Falha ao enviar alerta.")
                else:
                    logger.info(f"Alerta suprimido (cooldown ativo). Próximo em {alert_cooldown - (current_time - last_alert_time):.0f}s")
            
            # Para avisos não críticos, pode enviar sem cooldown
            elif "⚠️" in message and "ALERTA - Atenção" in message:
                logger.info("Enviando aviso não crítico ao Telegram...")
                send_telegram_message(message)
            
            logger.info(f"Próxima verificação em {CHECK_INTERVAL} segundos")
            logger.info("-" * 40)
            
            time.sleep(CHECK_INTERVAL)
            
        except KeyboardInterrupt:
            logger.info("Monitoramento interrompido pelo usuário.")
            send_telegram_message("⏹️ *Monitoramento Parado*\n\nO script foi interrompido manualmente.")
            break
        except Exception as e:
            logger.error(f"Erro inesperado no loop principal: {e}", exc_info=True)
            error_msg = f"🚨 *ERRO NO MONITOR*\n\nOcorreu um erro inesperado:\n{str(e)}\n\nVerifique os logs para detalhes."
            send_telegram_message(error_msg)
            time.sleep(60)  # Aguarda 1 minuto antes de tentar novamente


if __name__ == "__main__":
    main()
