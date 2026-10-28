"""Próxima ocorrência em horário local, sem repetir intervalos perdidos."""
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo


def next_occurrence(item, after):
    if item.get('frequency', 'once') == 'once':
        return None
    zone = ZoneInfo(item.get('timezone', 'America/Sao_Paulo'))
    anchor = datetime.fromisoformat(item.get('starts_at', item['run_at'])).astimezone(zone)
    local = after.astimezone(zone)
    for offset in range(8):
        date = local.date() + timedelta(days=offset)
        candidate = datetime.combine(date, anchor.time().replace(tzinfo=None), zone).astimezone(UTC)
        if candidate > after and (item['frequency'] == 'daily' or date.weekday() in item['weekdays']):
            return candidate.isoformat()
    raise ValueError('Não foi possível calcular a próxima ocorrência.')
