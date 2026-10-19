"""Gera a base de conhecimento treinada do CausaAI a partir dos pacotes de
validação (.md) exportados pelo próprio sistema.

Uso:  python3 gerar_base_treinada.py <pasta_com_os_md> <saida.js>

Regras de consolidação:
- Cada justificativa é reduzida a uma "chave de treino" (minúsculas, sem
  acentos, sem pontuação e com números mascarados como #), para que textos
  que só mudam data, hora ou número de pedido sejam reconhecidos como o mesmo.
- Votos em "Revisão manual necessária" são ignorados.
- Vence a categoria com mais validações; em empate, vence a validação mais
  recente; se o empate persistir (mesmo pacote), a chave fica marcada como
  ambígua e o sistema manda para revisão manual mostrando as duas opções.
"""
import glob, json, os, re, sys, unicodedata
from collections import defaultdict
from datetime import datetime

REVISAO = 'Revisão manual necessária'


def training_key(text):
    s = unicodedata.normalize('NFD', str(text or ''))
    s = ''.join(ch for ch in s if unicodedata.category(ch) != 'Mn').lower()
    s = re.sub(r'<br\s*/?>', ' ', s)
    s = re.sub(r'\d+', '#', s)
    s = re.sub(r'[^a-z#]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def parse(folder):
    rows = []
    for path in sorted(glob.glob(os.path.join(folder, '*'))):
        if not os.path.isfile(path):
            continue
        text = open(path, encoding='utf-8-sig').read()
        if '## Registros para aprendizado' not in text:
            continue
        m = re.search(r'Gerado em:\s*(\d{2}/\d{2}/\d{4}), (\d{2}:\d{2}:\d{2})', text)
        when = datetime.strptime(' '.join(m.groups()), '%d/%m/%Y %H:%M:%S') if m else datetime.min
        for line in text.split('## Registros para aprendizado', 1)[1].splitlines():
            if not line.startswith('| ') or line.startswith('| Aba') or line.startswith('| ---'):
                continue
            cells = [c.strip() for c in line.strip().strip('|').split(' | ')]
            if len(cells) < 10:
                continue
            rows.append({'final': cells[5], 'valid': cells[7], 'just': ' | '.join(cells[9:]).replace('\\|', '|'), 'when': when})
    return rows


def build(rows):
    votes = defaultdict(lambda: defaultdict(lambda: [0, datetime.min]))
    for r in rows:
        if r['valid'] != 'Sim' or r['final'] == REVISAO:
            continue
        key = training_key(r['just'])
        if not key:
            continue
        v = votes[key][r['final']]
        v[0] += 1
        v[1] = max(v[1], r['when'])
    base = []
    for key, cats in votes.items():
        ranked = sorted(cats.items(), key=lambda kv: (kv[1][0], kv[1][1]), reverse=True)
        top = ranked[0]
        entry = {'k': key, 'c': top[0], 'n': sum(v[0] for v in cats.values())}
        if len(ranked) > 1 and ranked[1][1][0] == top[1][0] and ranked[1][1][1] == top[1][1]:
            entry['alt'] = ranked[1][0]
        base.append(entry)
    base.sort(key=lambda e: (e['c'], e['k']))
    return base


if __name__ == '__main__':
    folder, out = sys.argv[1], sys.argv[2]
    rows = parse(folder)
    base = build(rows)
    last = max((r['when'] for r in rows), default=datetime.min)
    lines = ',\n'.join('  ' + json.dumps(e, ensure_ascii=False) for e in base)
    js = (f"// Base treinada gerada a partir de {len(rows)} registros validados em pacotes de\n"
          f"// validação (último pacote: {last:%d/%m/%Y}). Gerada por tools/gerar_base_treinada.py.\n"
          f"// k = chave de treino (texto normalizado, números mascarados como #),\n"
          f"// c = categoria validada, n = nº de validações, alt = categoria empatada.\n"
          f"const TRAINED_BASE_INFO = {{ registros: {len(rows)}, padroes: {len(base)}, atualizadoEm: '{last:%d/%m/%Y}' }};\n"
          f"const TRAINED_BASE = [\n{lines},\n];\n")
    open(out, 'w', encoding='utf-8').write(js)
    print(f'{len(rows)} registros -> {len(base)} padrões; empates: {sum(1 for e in base if "alt" in e)}')
