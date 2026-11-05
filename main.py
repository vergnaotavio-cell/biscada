"""
BISCA - menu, 1x1, 2x2, MODO APOSTA (roguelike com Curingas), tutorial leve, fonte do Balatro e MULTIPLAYER.

Requer pygame 2.x:  pip install pygame
Rodar:              python bisca_balatro.py

FONTE: coloque o arquivo m6x11plus.ttf (de Daniel Linssen, https://managore.itch.io/m6x11)
       dentro de uma pasta "fontes" ao lado deste script:
           bisca_balatro.py
           fontes/m6x11plus.ttf
       Se o arquivo não existir, o jogo usa a fonte padrão do pygame e continua funcionando.
       Crédito sugerido: "Fonte: m6x11plus por Daniel Linssen".

MULTIPLAYER (TCP, porta 5555)
  Menu > MULTIPLAYER > "Criar sala 1x1/2x2"  -> você vira o HOST e vê seu IP na tela
  Menu > MULTIPLAYER > "Entrar em uma sala"  -> digite o IP do host (ou IP:porta)
  O host aperta ENTER para começar; vagas vazias viram CPU. Só o host reinicia a partida.

  Como funciona: todos os jogadores recebem o baralho embaralhado pelo host e rodam a MESMA lógica
  (lockstep). Só trafegam as jogadas ("fulano jogou a carta X"). O host valida as jogadas dos
  clientes, comanda as CPUs e repassa tudo aos demais. Não é à prova de trapaça (o baralho vai para
  todos os clientes): foi feito para jogar com amigos.

Controles: clique na carta para jogar | R reinicia (offline/host) | M ou ESC volta ao menu
"""
import json
import math
import os
import queue
import random
import socket
import sys
import threading
from dataclasses import dataclass

import pygame

# ============================================================
# CONFIGURAÇÕES
# ============================================================
LARGURA, ALTURA = 1100, 720
FPS = 60
CARTA_L, CARTA_A = 100, 146
MAO_TAMANHO = 3
ATRASO_CPU = 650             # ms que a CPU "pensa"
ATRASO_VAZA = 950            # ms que a vaza fica visível antes de ser recolhida
MAX_PARTICULAS = 800
PORTA = 5555

CX, CY = LARGURA // 2, ALTURA // 2
PLACAR_POS = {0: (LARGURA - 130, 46), 1: (LARGURA - 130, 90)}

# Configuração de cada modo. "lados" diz onde cada jogador senta na mesa (baixo = você).
# A ordem da lista é a ordem de jogo (sentido horário na tela).
MODOS = {
    "1x1": {
        "titulo": "Bisca - 1x1",
        "nomes": ["Você", "CPU"],
        "equipes": [0, 1],
        "lados": ["baixo", "cima"],
        "baralho": (170, CY),
        "trunfo": (112, CY),
        "mesa": {0: (CX - 62, CY + 20), 1: (CX + 62, CY - 4)},
        "esc_mesa": 1.0,
        "placar": ("VOCÊ", "CPU"),
        "vitoria": "Você venceu!",
        "derrota": "A CPU venceu",
        "linha_fim": "Você {a}  x  {b} CPU",
    },
    "2x2": {
        "titulo": "Bisca - 2x2",
        "nomes": ["Você", "CPU Esq.", "Parceiro", "CPU Dir."],
        "equipes": [0, 1, 0, 1],
        "lados": ["baixo", "esq", "cima", "dir"],
        "baralho": (250, CY),
        "trunfo": (192, CY),
        "mesa": {0: (CX, CY + 40), 1: (CX - 100, CY - 10), 2: (CX, CY - 60), 3: (CX + 100, CY - 10)},
        "esc_mesa": 0.92,
        "placar": ("NÓS", "ELES"),
        "vitoria": "Sua dupla venceu!",
        "derrota": "A dupla rival venceu",
        "linha_fim": "Nós {a}  x  {b} Eles",
    },
}

# Cores dos naipes no estilo "alto contraste" do Balatro (símbolo, valor e miolo da carta)
COR_NAIPE = {
    "copas": (226, 62, 62),      # vermelho
    "ouros": (244, 140, 24),     # laranja
    "paus": (36, 104, 214),      # azul
    "espadas": (50, 44, 82),     # roxo-escuro (quase preto)
}
FUNDO_BASE = (14, 46, 44)
FUNDO_BRACO = (20, 64, 58)
BRANCO = (245, 245, 240)
DOURADO = (240, 200, 70)
CINZA = (150, 150, 175)
VERDE = (120, 230, 150)
AZUL_EQ = (110, 165, 255)        # sua equipe
VERMELHO_EQ = (255, 105, 115)    # equipe rival
CORES_TITULO = [(255, 80, 90), (255, 160, 40), (240, 200, 70), (60, 200, 255), (190, 120, 255)]

# Cores neon de alto contraste por naipe (partículas)
CORES_NAIPE = {
    "paus": [(0, 230, 255), (120, 255, 255), (0, 150, 255)],
    "ouros": [(255, 150, 20), (255, 210, 60), (255, 100, 0)],
    "copas": [(255, 50, 110), (255, 130, 170), (255, 20, 60)],
    "espadas": [(170, 90, 255), (220, 170, 255), (90, 60, 255)],
}

# ============================================================
# 0) FONTE DO BALATRO (m6x11plus) - carregada SEMPRE do arquivo, nunca do sistema
# ============================================================
def recurso(rel):
    """Caminho de um arquivo do jogo: funciona no .py e no .exe do PyInstaller."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


# Fontes
FONTE_ARQUIVOS = [("m6x11plus.ttf", 18), ("m6x11.ttf", 16)]
FONTE = {"path": None, "unidade": 0, "pixel": False}

for _nome, _un in FONTE_ARQUIVOS:
    _p = recurso(_nome)
    if os.path.isfile(_p):
        FONTE.update(path=_p, unidade=_un, pixel=True)
        break


# Capa do jogo
CAPA_ARQUIVO = "icon.png"
CAPA = recurso(CAPA_ARQUIVO) if os.path.isfile(recurso(CAPA_ARQUIVO)) else None

def fonte(mult, fallback):
    """mult = múltiplo inteiro do tamanho-base da fonte pixel; fallback = tamanho da fonte padrão."""
    if FONTE["pixel"]:
        try:
            return pygame.font.Font(FONTE["path"], FONTE["unidade"] * mult)
        except (OSError, pygame.error):
            FONTE["pixel"] = False
    return pygame.font.Font(None, fallback)


# ============================================================
# 1) LÓGICA DO JOGO (sem pygame)
# ============================================================
NAIPES = ["copas", "ouros", "paus", "espadas"]
VALORES = ["2", "3", "4", "5", "6", "Q", "J", "K", "7", "A"]  # do mais fraco ao mais forte
PONTOS = {"A": 11, "7": 10, "K": 4, "J": 3, "Q": 2}


@dataclass(frozen=True)
class Carta:
    naipe: str
    valor: str

    @property
    def pontos(self):
        return PONTOS.get(self.valor, 0)

    @property
    def forca(self):
        return VALORES.index(self.valor)

    @property
    def vermelha(self):
        return self.naipe in ("copas", "ouros")


class Jogador:
    """tipo: 'humano' (este computador), 'cpu' (IA rodando aqui) ou 'remoto' (jogada vem da rede)."""

    def __init__(self, nome, equipe, tipo="cpu"):
        self.nome = nome
        self.equipe = equipe
        self.tipo = tipo
        self.mao = []


def novo_baralho():
    b = [Carta(nm, v) for nm in NAIPES for v in VALORES]
    random.shuffle(b)
    return b


class Partida:
    def __init__(self, jogadores, baralho=None, regras=None):
        self.jogadores = jogadores
        self.n = len(jogadores)
        self.regras = dict(regras or {})      # regras especiais do Modo Aposta (chefes etc.)
        # O baralho é consumido com pop() (fim da lista); o índice 0 é o fundo = carta do trunfo.
        self.baralho = list(baralho) if baralho is not None else novo_baralho()
        self.carta_trunfo = self.baralho[0]
        self.trunfo = self.carta_trunfo.naipe
        # naipes que contam como trunfo (regras podem remover ou dobrar o trunfo)
        self.trunfos = {self.trunfo}
        if self.regras.get("sem_trunfo"):
            self.trunfos = set()
        elif self.regras.get("dois_trunfos"):
            self.trunfos.add(NAIPES[(NAIPES.index(self.trunfo) + 1) % len(NAIPES)])
        self.pontos_zero = set(self.regras.get("pontos_zero", ()))
        self.pontos = {j.equipe: 0 for j in jogadores}
        self.vazas_feitas = 0
        for _ in range(MAO_TAMANHO):
            for j in jogadores:
                j.mao.append(self.baralho.pop())
        self.vez = 0          # índice de quem joga agora
        self.mesa = []        # [(indice_jogador, carta), ...] da vaza atual

    def rotacionar(self, k):
        """Gira a ordem dos jogadores para o jogador k virar o índice 0 (visão local no online).
        A ordem de jogo (ciclo) não muda, só o ponto de vista. Chamar logo após a distribuição."""
        self.jogadores = self.jogadores[k:] + self.jogadores[:k]
        self.vez = (self.vez - k) % self.n

    # ---------- consultas ----------
    @property
    def vaza_completa(self):
        return len(self.mesa) == self.n

    def eh_trunfo(self, c):
        return c.naipe in self.trunfos

    def forca_de(self, c):
        """Força da carta (a regra 'invertido' troca a ordem: o 2 vira o mais forte)."""
        return len(VALORES) - 1 - c.forca if self.regras.get("invertido") else c.forca

    def pontos_de(self, c):
        """Pontos da carta (a regra 'pontos_zero' zera valores, ex.: Ases)."""
        return 0 if c.valor in self.pontos_zero else c.pontos

    def vencedor_de(self, jogadas):
        """Índice do jogador que vence um conjunto de jogadas [(idx, carta), ...]."""
        naipe_aberto = jogadas[0][1].naipe

        def chave(jogada):
            c = jogada[1]
            if self.eh_trunfo(c):
                return (2, self.forca_de(c))
            if c.naipe == naipe_aberto:
                return (1, self.forca_de(c))
            return (0, self.forca_de(c))

        return max(jogadas, key=chave)[0]

    def vencedor_atual(self):
        return self.vencedor_de(self.mesa)

    def terminou(self):
        return not self.baralho and all(not j.mao for j in self.jogadores)

    def resultado(self):
        """Retorna (pontos_equipe0, pontos_equipe1)."""
        return self.pontos[0], self.pontos[1]

    # ---------- ações ----------
    def jogar(self, idx, carta):
        self.jogadores[idx].mao.remove(carta)
        self.mesa.append((idx, carta))
        if not self.vaza_completa:
            self.vez = (self.vez + 1) % self.n

    def resolver_vaza(self):
        venc = self.vencedor_atual()
        pts = sum(self.pontos_de(c) for _, c in self.mesa)
        self.pontos[self.jogadores[venc].equipe] += pts
        self.mesa = []
        self.vazas_feitas += 1
        # quem ganhou compra primeiro (a última compra leva a carta do trunfo)
        for i in range(self.n):
            j = self.jogadores[(venc + i) % self.n]
            if self.baralho:
                j.mao.append(self.baralho.pop())
        self.vez = venc
        return venc, pts


def montar_partida_online(modo, k, humanos, deck, host):
    """Monta a Partida vista pelo jogador do assento global k.
    humanos = assentos globais ocupados por pessoas; os demais são CPUs (comandadas pelo host).
    Todos os computadores chamam isto com os mesmos dados e obtêm a mesma partida (lockstep)."""
    cfg = MODOS[modo]
    n = len(cfg["nomes"])
    eq_g = cfg["equipes"]
    jogs = []
    for g in range(n):
        rel = (g - k) % n
        if g == k:
            nome, tipo = "Você", "humano"
        elif g in humanos:
            nome, tipo = ("Host" if g == 0 else f"Jogador {g + 1}"), "remoto"
        else:
            nome, tipo = cfg["nomes"][rel], ("cpu" if host else "remoto")
        # equipe 0 = a minha, equipe 1 = a rival (o placar sempre mostra "minha equipe" em cima)
        jogs.append(Jogador(nome, 0 if eq_g[g] == eq_g[k] else 1, tipo))
    p = Partida(jogs, baralho=deck)    # distribui na ordem global (igual para todos)
    p.rotacionar(k)                     # e só então gira para a visão local
    return p


# ---------- IA simples da CPU (com "perfil" de personalidade no Modo Aposta) ----------
def custo(partida, carta):
    """Quanto a CPU 'dói' em gastar a carta (menor = mais descartável)."""
    return partida.pontos_de(carta) * 10 + partida.forca_de(carta) + (100 if partida.eh_trunfo(carta) else 0)


def cpu_escolher(partida, idx, perfil=None):
    """perfil (opcional): trunfo_min (pontos na mesa para gastar trunfo), aleatorio (chance de jogar
    qualquer carta) e abre_alto (chance de abrir a vaza com carta forte)."""
    perfil = perfil or {}
    jog = partida.jogadores
    mao = jog[idx].mao
    barata = lambda c: custo(partida, c)

    if perfil.get("aleatorio") and random.random() < perfil["aleatorio"]:
        return random.choice(mao)

    if not partida.mesa:  # abrindo a vaza
        if perfil.get("abre_alto") and random.random() < perfil["abre_alto"]:
            return max(mao, key=lambda c: (not partida.eh_trunfo(c), partida.forca_de(c)))
        return min(mao, key=barata)

    pts_mesa = sum(partida.pontos_de(c) for _, c in partida.mesa)
    venc = partida.vencedor_atual()
    ultimo = len(partida.mesa) == partida.n - 1

    # o parceiro está ganhando: se a vaza está segura, joga pontos (sem gastar trunfo)
    if jog[venc].equipe == jog[idx].equipe:
        carta_parc = next(c for i, c in partida.mesa if i == venc)
        segura = ultimo or (partida.eh_trunfo(carta_parc) and partida.forca_de(carta_parc) >= VALORES.index("K"))
        if segura:
            carregar = [c for c in mao if not partida.eh_trunfo(c) and partida.pontos_de(c) > 0]
            if carregar:
                return max(carregar, key=lambda c: (partida.pontos_de(c), -partida.forca_de(c)))
        return min(mao, key=barata)

    vencedoras = [c for c in mao if partida.vencedor_de(partida.mesa + [(idx, c)]) == idx]
    if vencedoras:
        melhor = min(vencedoras, key=barata)
        # só gasta trunfo se a vaza valer a pena (o perfil muda esse limite)
        if not partida.eh_trunfo(melhor) or pts_mesa >= perfil.get("trunfo_min", 3):
            return melhor
    return min(mao, key=barata)


# ============================================================
# 1b) REDE (sem pygame): TCP + JSON por linha
# ============================================================
def carta_json(c):
    return [c.naipe, c.valor]


def carta_de(x):
    """Valida e converte [naipe, valor] vindo da rede; None se for inválido."""
    if isinstance(x, (list, tuple)) and len(x) == 2 and x[0] in NAIPES and x[1] in VALORES:
        return Carta(x[0], x[1])
    return None


def ip_local():
    """IP da máquina na rede local (não envia nada pela rede)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class Conexao:
    """Um socket com uma thread leitora; as mensagens chegam numa fila (thread-safe)."""

    def __init__(self, sock):
        self.sock = sock
        self.fila = queue.Queue()
        self.vivo = True
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        threading.Thread(target=self._ler, daemon=True).start()

    def _ler(self):
        buf = b""
        try:
            while True:
                dados = self.sock.recv(4096)
                if not dados:
                    break
                buf += dados
                if len(buf) > 1_000_000:       # proteção contra lixo
                    break
                while b"\n" in buf:
                    linha, buf = buf.split(b"\n", 1)
                    if linha.strip():
                        try:
                            msg = json.loads(linha.decode("utf-8"))
                        except ValueError:
                            continue
                        if isinstance(msg, dict):
                            self.fila.put(msg)
        except OSError:
            pass
        self.vivo = False
        self.fila.put({"t": "desconectou"})

    def enviar(self, msg):
        if not self.vivo:
            return False
        try:
            self.sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))
            return True
        except OSError:
            self.vivo = False
            return False

    def receber(self):
        out = []
        while True:
            try:
                out.append(self.fila.get_nowait())
            except queue.Empty:
                return out

    def fechar(self):
        self.vivo = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class Servidor:
    """Aceita conexões numa thread; as novas conexões ficam numa fila."""

    def __init__(self, porta=PORTA):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name != "nt":
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", porta))
        self.sock.listen(8)
        self.sock.settimeout(0.5)
        self.porta = porta
        self.novas = queue.Queue()
        self.ativo = True
        threading.Thread(target=self._aceitar, daemon=True).start()

    def _aceitar(self):
        while self.ativo:
            try:
                s, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            s.settimeout(None)
            self.novas.put(Conexao(s))

    def pegar_novas(self):
        out = []
        while True:
            try:
                out.append(self.novas.get_nowait())
            except queue.Empty:
                return out

    def fechar(self):
        self.ativo = False
        try:
            self.sock.close()
        except OSError:
            pass


class SalaHost:
    """Lado do host: distribui assentos, repassa mensagens e avisa quem entra/sai."""

    def __init__(self, modo, porta=PORTA):
        self.modo = modo
        self.n = len(MODOS[modo]["nomes"])
        self.servidor = Servidor(porta)
        self.conexoes = {}          # assento global (1..n-1) -> Conexao
        self.iniciada = False

    @property
    def ip(self):
        return ip_local()

    def humanos(self):
        return [0] + sorted(self.conexoes)

    def atualizar(self):
        """Chamar todo frame. Retorna eventos [(assento, mensagem)] (inclui {'t':'saiu'})."""
        mudou = False
        for conn in self.servidor.pegar_novas():
            livres = [a for a in range(1, self.n) if a not in self.conexoes]
            if self.iniciada or not livres:
                conn.enviar({"t": "recusado", "motivo": "Sala cheia ou partida em andamento"})
                conn.fechar()
                continue
            a = livres[0]
            self.conexoes[a] = conn
            conn.enviar({"t": "bemvindo", "assento": a, "modo": self.modo})
            mudou = True
        eventos = []
        for a, conn in list(self.conexoes.items()):
            for msg in conn.receber():
                if msg.get("t") == "desconectou":
                    if self.conexoes.get(a) is conn:
                        del self.conexoes[a]
                    conn.fechar()
                    eventos.append((a, {"t": "saiu"}))
                    mudou = True
                else:
                    eventos.append((a, msg))
        if mudou:
            self.enviar_lobby()
        return eventos

    def enviar_lobby(self):
        self.transmitir({"t": "lobby", "modo": self.modo, "conectados": sorted(self.conexoes)})

    def transmitir(self, msg, exceto=None):
        for a, conn in list(self.conexoes.items()):
            if a != exceto:
                conn.enviar(msg)

    def iniciar(self, deck):
        """Manda o baralho embaralhado e os assentos a todos (também usado para reiniciar)."""
        self.iniciada = True
        humanos = self.humanos()
        for a, conn in list(self.conexoes.items()):
            conn.enviar({"t": "inicio", "modo": self.modo, "assento": a,
                         "baralho": [carta_json(c) for c in deck], "humanos": humanos})

    def fechar(self):
        for conn in list(self.conexoes.values()):
            conn.fechar()
        self.conexoes.clear()
        self.servidor.fechar()


class EntradaCliente:
    """Lado do cliente: conecta numa thread (não trava a janela) e guarda o estado do lobby."""

    def __init__(self, destino):
        host, _, porta = destino.strip().partition(":")
        self.host = host or "127.0.0.1"
        try:
            self.porta = int(porta) if porta else PORTA
        except ValueError:
            self.porta = PORTA
        self.estado = "conectando"     # conectando | ok | erro
        self.erro = ""
        self.conn = None
        self.assento = None
        self.modo = None
        self.conectados = []
        self.cancelado = False
        threading.Thread(target=self._conectar, daemon=True).start()

    def _conectar(self):
        try:
            sock = socket.create_connection((self.host, self.porta), timeout=5)
            sock.settimeout(None)
        except OSError:
            self.erro = "Não foi possível conectar (confira o IP, a porta e o firewall)"
            self.estado = "erro"
            return
        if self.cancelado:
            sock.close()
            return
        self.conn = Conexao(sock)
        self.estado = "ok"

    def fechar(self):
        self.cancelado = True
        if self.conn:
            self.conn.fechar()


# ============================================================
# 1c) SAVE, DICAS E MODO APOSTA (lógica, sem pygame)
# ============================================================
AZUL_FICHA = (90, 175, 255)
COR_MULT = (255, 95, 95)
COR_DINHEIRO = (120, 230, 150)


def quebrar(fonte_, txt, largura):
    """Quebra um texto em linhas que caibam na largura (em pixels) da fonte."""
    linhas, atual = [], ""
    for palavra in txt.split():
        teste = (atual + " " + palavra).strip()
        if not atual or fonte_.size(teste)[0] <= largura:
            atual = teste
        else:
            linhas.append(atual)
            atual = palavra
    if atual:
        linhas.append(atual)
    return linhas


# ---------- SAVE (tutorial feito, melhor run...) ----------
SAVE_PADRAO = {"vistas": [], "melhor_nivel": 0, "runs": 0, "vitorias": 0}


def caminho_save():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "BiscaBalatro", "save.json")


def carregar_save():
    dados = {k: (list(v) if isinstance(v, list) else v) for k, v in SAVE_PADRAO.items()}
    try:
        with open(caminho_save(), "r", encoding="utf-8") as f:
            lido = json.load(f)
        if isinstance(lido, dict):
            for k, padrao in SAVE_PADRAO.items():
                if k in lido and type(lido[k]) is type(padrao):
                    dados[k] = lido[k]
    except (OSError, ValueError):
        pass
    return dados


def salvar_save(dados):
    try:
        p = caminho_save()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(dados, f)
    except OSError:
        pass


# ---------- DICAS: cada uma aparece UMA vez (depois o HUD fica limpo) ----------
TIPS = {
    "basico": [
        {"alvo": None, "linhas": ["BISCA EM 20 SEGUNDOS", "Cada carta vale pontos:", "A=11   7=10   K=4   J=3   Q=2",
                                  "As outras valem 0. Total: 120 pontos."]},
        {"alvo": "trunfo", "linhas": ["TRUNFO", "O naipe do canto vence qualquer", "carta dos outros naipes."]},
        {"alvo": "mao", "linhas": ["SUA VEZ", "Clique em uma carta para jogar.", "Vence a vaza o trunfo mais alto ou,",
                                   "sem trunfo, a maior do naipe aberto."]},
    ],
    "vaza1": [
        {"alvo": "placar", "linhas": ["BOA!", "Quem vence a vaza leva os pontos", "e compra primeiro.", "",
                                      "Agora os textos somem:", "brilho = sua vez, pontinhos = espera.",
                                      "F1 mostra as dicas de novo."]},
    ],
    "rg_aposta": [
        {"alvo": None, "linhas": ["MODO APOSTA", "Cada confronto é uma mão de Bisca.", "Bata a META de pontos para vencer.",
                                  "Perdeu? Perde vidas. Sem vidas, fim da run.", "A cada vitória, nível e meta sobem."]},
    ],
    "rg_pontos": [
        {"alvo": "placar", "linhas": ["FICHAS x MULT", "Vaza vencida = fichas (pontos das cartas)", "vezes o seu multiplicador.",
                                      "Curingas turbinam os dois."]},
    ],
    "rg_loja": [
        {"alvo": None, "linhas": ["LOJA", "Clique numa carta para comprar.", "Botão direito ou S vende um Curinga.",
                                  "A cada $5 guardados rende $1 de juros."]},
    ],
}
ANCORAS = {"trunfo": (82, 128), "placar": (LARGURA - 130, 128), "mao": (CX, ALTURA - 205)}


# ---------- MODO APOSTA: constantes de balanceamento (mexa aqui para ajustar a dificuldade) ----------
NIVEL_FINAL = 6
META_BASE = {1: 36, 2: 60, 3: 92, 4: 135, 5: 200, 6: 300}   # pontos (fichas x mult) para bater a meta
FATOR_ETAPA = [1.0, 1.35, 1.7]                                # pequena, grande, chefe
ETAPA_CURTA = ["PEQUENA", "GRANDE", "CHEFE"]
RECOMPENSA_ETAPA = [3, 4, 6]
# (nome, multiplicador da meta, multiplicador da recompensa, vidas perdidas se falhar)
APOSTAS = [("Segura", 1.0, 1, 1), ("Alta", 1.3, 2, 1), ("Tudo", 1.7, 3, 2)]
MAX_CURINGAS = 5
MAX_VIDAS = 5
DINHEIRO_INICIAL = 4
VIDAS_INICIAIS = 3

# cor e peso de sorteio de cada raridade
RARIDADES = {"comum": ((200, 200, 215), 70), "incomum": ((90, 200, 255), 25), "rara": ((255, 150, 60), 5)}

# Curingas: cartas especiais compradas na loja. "valores" muda os pontos de uma carta nas vazas que
# VOCÊ vence; "revela" mostra a mão do rival. Os efeitos numéricos estão em EFEITOS (mais abaixo).
CURINGAS = {
    "sete_ouro": dict(nome="Sete de Ouro", rar="comum", custo=4, naipe="ouros",
                      desc="+10 fichas ao vencer uma vaza que tenha um 7 na mesa."),
    "gato_preto": dict(nome="Gato Preto", rar="comum", custo=4, naipe="espadas",
                       desc="+0.5 de mult ao vencer uma vaza com carta de trunfo."),
    "zero_esquerda": dict(nome="Zero à Esquerda", rar="comum", custo=4, naipe="paus",
                          desc="Vencer com uma carta de 0 pontos: +6 fichas e +0.5 de mult."),
    "mao_vaca": dict(nome="Mão de Vaca", rar="comum", custo=5, naipe="ouros",
                     desc="Ganha $1 por vaza que você perde. Perder também rende."),
    "vendaval": dict(nome="Vendaval", rar="comum", custo=5, naipe="espadas",
                     desc="Cada vaza que o rival ganha dá +0.15 de mult até o fim da mão."),
    "boto": dict(nome="Boto Cor-de-Rosa", rar="comum", custo=5, naipe="copas", valores={"Q": 8},
                 desc="Damas (Q) valem 8 pontos nas mãos que você vence."),
    "malandro": dict(nome="Valete Malandro", rar="comum", custo=5, naipe="paus", valores={"J": 7},
                     desc="Valetes (J) valem 7 pontos nas mãos que você vence."),
    "compadre_rico": dict(nome="Compadre Rico", rar="comum", custo=5, naipe="ouros",
                          desc="Ganha $3 extra ao vencer um confronto."),
    "cartola": dict(nome="Cartola", rar="incomum", custo=6, naipe="espadas",
                    desc="+0.25 de mult por trunfo na sua mão ao vencer uma vaza. Guarde trunfos!"),
    "rancor": dict(nome="Rancor do Compadre", rar="incomum", custo=7, naipe="copas",
                   desc="Cada vaza perdida dá +0.1 de mult PERMANENTE até o fim da run."),
    "saci": dict(nome="Saci Pererê", rar="incomum", custo=6, naipe="paus",
                 desc="A primeira vaza de cada mão vale x2."),
    "ultima_danca": dict(nome="Última Dança", rar="incomum", custo=6, naipe="copas",
                         desc="A última vaza da mão vale x3."),
    "sorte_grande": dict(nome="Sorte Grande", rar="incomum", custo=6, naipe="ouros",
                         desc="25% de chance de x2 ao vencer uma vaza."),
    "cobrador": dict(nome="Caipora Cobradora", rar="incomum", custo=6, naipe="paus",
                     desc="Vencer um trunfo do rival com um trunfo seu rende $2."),
    "olho_vidro": dict(nome="Olho de Vidro", rar="incomum", custo=8, naipe="espadas", revela=True,
                       desc="Revela as cartas da mão do rival."),
    "mestre_sala": dict(nome="Mestre-Sala", rar="rara", custo=9, naipe="copas",
                        desc="Se você abriu a vaza e venceu: x2."),
    "capote_dourado": dict(nome="Capote Dourado", rar="rara", custo=9, naipe="ouros",
                           desc="Mãos seguidas vencidas: +x0.25 cada (máx. x3)."),
    "jogador": dict(nome="Jogador Compulsivo", rar="rara", custo=8, naipe="espadas",
                    desc="+0.5 de mult por nível de aposta acima da Segura."),
}


def _log(ctx, st, txt, cor):
    ctx["log"].append((st["i"], txt, cor))


def _ef_sete_ouro(ctx, st):
    if ctx["venci"] and any(c.valor == "7" for _, c in ctx["mesa"]):
        ctx["chips"] += 10
        _log(ctx, st, "+10", AZUL_FICHA)


def _ef_gato_preto(ctx, st):
    if ctx["venci"] and ctx["minha_trunfo"]:
        ctx["mult"] += 0.5
        _log(ctx, st, "+0.5 mult", COR_MULT)


def _ef_zero_esquerda(ctx, st):
    if ctx["venci"] and ctx["pontos_de"](ctx["minha"]) == 0:
        ctx["chips"] += 6
        ctx["mult"] += 0.5
        _log(ctx, st, "+6 +0.5", COR_MULT)


def _ef_mao_vaca(ctx, st):
    if not ctx["venci"]:
        ctx["dinheiro"] += 1
        _log(ctx, st, "+$1", COR_DINHEIRO)


def _ef_vendaval(ctx, st):
    if ctx["venci"]:
        if st.get("mao", 0) > 0:
            ctx["mult"] += st["mao"]
            _log(ctx, st, f"+{st['mao']:.2f}", COR_MULT)
    else:
        st["mao"] = st.get("mao", 0.0) + 0.15


def _ef_cartola(ctx, st):
    if ctx["venci"] and ctx["trunfos_mao"]:
        add = 0.25 * ctx["trunfos_mao"]
        ctx["mult"] += add
        _log(ctx, st, f"+{add:.2f}", COR_MULT)


def _ef_rancor(ctx, st):
    if ctx["venci"]:
        if st.get("acum", 0) > 0:
            ctx["mult"] += st["acum"]
            _log(ctx, st, f"+{st['acum']:.1f}", COR_MULT)
    else:
        st["acum"] = st.get("acum", 0.0) + 0.1


def _ef_saci(ctx, st):
    if ctx["venci"] and ctx["vaza_num"] == 1:
        ctx["xmult"] *= 2
        _log(ctx, st, "x2", COR_MULT)


def _ef_ultima_danca(ctx, st):
    if ctx["venci"] and ctx["ultima"]:
        ctx["xmult"] *= 3
        _log(ctx, st, "x3", COR_MULT)


def _ef_sorte_grande(ctx, st):
    if ctx["venci"] and ctx["rng"].random() < 0.25:
        ctx["xmult"] *= 2
        _log(ctx, st, "x2!", COR_MULT)


def _ef_cobrador(ctx, st):
    if ctx["venci"] and ctx["rival_trunfo"] and ctx["minha_trunfo"]:
        ctx["dinheiro"] += 2
        _log(ctx, st, "+$2", COR_DINHEIRO)


def _ef_mestre_sala(ctx, st):
    if ctx["venci"] and ctx["abri"]:
        ctx["xmult"] *= 2
        _log(ctx, st, "x2", COR_MULT)


def _ef_capote_dourado(ctx, st):
    if ctx["venci"] and ctx["seq"] >= 2:
        x = min(3.0, 1 + 0.25 * (ctx["seq"] - 1))
        ctx["xmult"] *= x
        _log(ctx, st, f"x{x:.2f}", COR_MULT)


def _ef_jogador(ctx, st):
    if ctx["venci"] and ctx["aposta"] > 0:
        add = 0.5 * ctx["aposta"]
        ctx["mult"] += add
        _log(ctx, st, f"+{add:g} mult", COR_MULT)


EFEITOS = {
    "sete_ouro": _ef_sete_ouro, "gato_preto": _ef_gato_preto, "zero_esquerda": _ef_zero_esquerda,
    "mao_vaca": _ef_mao_vaca, "vendaval": _ef_vendaval, "cartola": _ef_cartola, "rancor": _ef_rancor,
    "saci": _ef_saci, "ultima_danca": _ef_ultima_danca, "sorte_grande": _ef_sorte_grande,
    "cobrador": _ef_cobrador, "mestre_sala": _ef_mestre_sala, "capote_dourado": _ef_capote_dourado,
    "jogador": _ef_jogador,
}


def _fim_compadre_rico(ctx, st):
    ctx["dinheiro"] += 3
    ctx["linhas"].append(("Compadre Rico", "+$3", COR_DINHEIRO))


EFEITOS_FIM = {"compadre_rico": _fim_compadre_rico}


# ---------- Oponentes procedurais ----------
PERFIS = {
    "sovina": dict(nome="Sovina", desc="Guarda trunfos para mãos gordas.", trunfo_min=9),
    "esbanjador": dict(nome="Esbanjador", desc="Joga trunfo à toa.", trunfo_min=0),
    "esperto": dict(nome="Esperto", desc="Joga na lógica, sem surpresas.", trunfo_min=3),
    "imprevisivel": dict(nome="Imprevisível", desc="Às vezes joga qualquer carta.", trunfo_min=3, aleatorio=0.3),
    "valentao": dict(nome="Valentão", desc="Abre a mão com carta forte.", trunfo_min=3, abre_alto=0.6),
}
REGRAS = {
    "dois_trunfos": ("Dois Trunfos", "Um segundo naipe também vale como trunfo."),
    "sem_as": ("Ás Amaldiçoado", "Ases valem 0 pontos."),
    "sem_sete": ("Sete Maldito", "Setes valem 0 pontos."),
    "taxa": ("Taxa do Chefe", "Cada mão vencida rende 4 fichas a menos."),
    "invertido": ("Ordem Invertida", "O 2 é a carta mais forte e o Ás a mais fraca."),
    "sem_trunfo": ("Sem Trunfo", "Nenhum naipe é trunfo nesta mão."),
    "silencio": ("Silêncio", "Seu primeiro Curinga fica desativado."),
}
REGRAS_GRANDE = ["dois_trunfos", "sem_as", "sem_sete"]
REGRAS_CHEFE = ["taxa", "invertido", "sem_trunfo", "silencio", "dois_trunfos", "sem_as"]
_MASC = (["Seu", "Mestre", "Compadre", "Coronel", "Frei", "Tio", "Doutor"],
         ["Zé", "Bento", "Tião", "Nonato", "Gaudêncio", "Ludovico", "Jurandir", "Cacau"])
_FEM = (["Dona", "Comadre", "Tia", "Vó", "Doutora", "Sinhá"],
        ["Quitéria", "Lourdes", "Dida", "Maroca", "Zefa", "Neide", "Ceição", "Marinalva"])
_APELIDOS = ["do Trunfo", "Pé-Frio", "da Sorte", "Sete-Belo", "Mão-de-Onça", "Sem-Dente", "Lampião",
             "do Baralho", "Cara-de-Pau"]


@dataclass(frozen=True)
class Oponente:
    nome: str
    perfil: str
    naipe: str


@dataclass(frozen=True)
class Confronto:
    nivel: int
    etapa: int
    oponente: Oponente
    regra: object = None      # chave de REGRAS ou None


def gerar_oponente(rng):
    titulos, nomes = rng.choice((_MASC, _FEM))
    nome = f"{rng.choice(titulos)} {rng.choice(nomes)}"
    if rng.random() < 0.7:
        nome += " " + rng.choice(_APELIDOS)
    return Oponente(nome, rng.choice(sorted(PERFIS)), rng.choice(NAIPES))


class Run:
    """Uma 'run' do Modo Aposta: 6 níveis x 3 confrontos (pequena, grande, chefe), loja entre eles."""

    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.nivel, self.etapa = 1, 0
        self.dinheiro, self.vidas = DINHEIRO_INICIAL, VIDAS_INICIAIS
        self.curingas = []          # [{"id":..., "acum":..., "mao":...}]
        self.aposta = 0
        self.vitorias = 0
        self.score = 0
        self.seq = self.perdidas = self.vazas = 0
        self.fim = None             # None | "derrota" | "vitoria"
        self.oferta, self.reroll_n, self.vida_comprada = [], 0, False
        self.confrontos = []
        self.gerar_nivel()

    # ---------- níveis e confrontos ----------
    def gerar_nivel(self):
        rng = self.rng
        conf, usadas = [], set()
        for etapa in range(3):
            regra = None
            if etapa == 1 and rng.random() < 0.5:
                regra = rng.choice(REGRAS_GRANDE)
            elif etapa == 2:
                pool = [r for r in REGRAS_CHEFE if r not in usadas
                        and not (self.nivel == 1 and r in ("silencio", "taxa"))]
                regra = rng.choice(pool)
            if regra:
                usadas.add(regra)
            conf.append(Confronto(self.nivel, etapa, gerar_oponente(rng), regra))
        self.confrontos = conf

    @property
    def confronto(self):
        return self.confrontos[self.etapa]

    def regras_partida(self):
        """Regras que a Partida (lógica da mão) precisa conhecer."""
        r = self.confronto.regra
        if r in ("sem_trunfo", "dois_trunfos", "invertido"):
            return {r: True}
        if r == "sem_as":
            return {"pontos_zero": ["A"]}
        if r == "sem_sete":
            return {"pontos_zero": ["7"]}
        return {}

    def meta(self, aposta=None):
        a = self.aposta if aposta is None else aposta
        c = self.confronto
        return int(round(META_BASE[c.nivel] * FATOR_ETAPA[c.etapa] * APOSTAS[a][1]))

    def recompensa_base(self, aposta=None):
        a = self.aposta if aposta is None else aposta
        c = self.confronto
        return (RECOMPENSA_ETAPA[c.etapa] + c.nivel - 1) * APOSTAS[a][2]

    # ---------- curingas ----------
    def ativos(self):
        lista = list(self.curingas)
        if self.confronto.regra == "silencio" and lista:
            lista = lista[1:]        # o primeiro Curinga fica mudo
        return lista

    def valores_override(self):
        ov = {}
        for st in self.ativos():
            ov.update(CURINGAS[st["id"]].get("valores", {}))
        return ov

    def revela(self):
        return any(CURINGAS[st["id"]].get("revela") for st in self.ativos())

    # ---------- confronto ----------
    def iniciar_confronto(self, aposta):
        self.aposta = aposta
        self.score = 0
        self.seq = self.perdidas = self.vazas = 0
        for st in self.curingas:
            st["mao"] = 0.0

    def processar_vaza(self, p, venc):
        """Pontua uma mão ANTES de p.resolver_vaza(). venc = índice local do vencedor (0 = você).
        Retorna {'venci','chips','mult','ganho','dinheiro','log'}."""
        mesa = list(p.mesa)
        venci = venc == 0
        minha = next(c for i, c in mesa if i == 0)
        rival = next(c for i, c in mesa if i != 0)
        self.vazas += 1
        if venci:
            self.seq += 1
        else:
            self.seq = 0
            self.perdidas += 1
        ultima = not p.baralho and all(not j.mao for j in p.jogadores)
        ov = self.valores_override()
        chips = sum(ov.get(c.valor, p.pontos_de(c)) for _, c in mesa) if venci else 0
        ctx = dict(venci=venci, abri=(mesa[0][0] == 0), mesa=mesa, minha=minha, rival=rival, trunfo=p.trunfo,
                   minha_trunfo=p.eh_trunfo(minha), rival_trunfo=p.eh_trunfo(rival), pontos_de=p.pontos_de,
                   chips=chips, mult=1.0, xmult=1.0, dinheiro=0, seq=self.seq, perdidas=self.perdidas,
                   vaza_num=self.vazas, ultima=ultima, aposta=self.aposta, rng=self.rng, log=[],
                   trunfos_mao=sum(1 for c in p.jogadores[0].mao if p.eh_trunfo(c)))
        for i, st in enumerate(self.curingas):
            st["i"] = i
        for st in self.ativos():
            fn = EFEITOS.get(st["id"])
            if fn:
                fn(ctx, st)
        ganho = 0
        if venci:
            if self.confronto.regra == "taxa":
                ctx["chips"] = max(0, ctx["chips"] - 4)
            ganho = int(round(ctx["chips"] * ctx["mult"] * ctx["xmult"]))
        self.score += ganho
        self.dinheiro += ctx["dinheiro"]
        return dict(venci=venci, chips=ctx["chips"], mult=round(ctx["mult"] * ctx["xmult"], 2),
                    ganho=ganho, dinheiro=ctx["dinheiro"], log=ctx["log"])

    def fechar_confronto(self):
        """Encerra o confronto: paga recompensa ou tira vidas, e avança (etapa/nível/fim)."""
        meta = self.meta()
        venceu = self.score >= meta
        res = {"venceu": venceu, "score": self.score, "meta": meta, "linhas": [], "total": 0}
        if venceu:
            base = self.recompensa_base()
            sobra = min(3, int((self.score - meta) / max(1.0, meta * 0.25)))
            juros = min(5, self.dinheiro // 5)
            ctxf = {"dinheiro": 0, "linhas": []}
            for st in self.ativos():
                fn = EFEITOS_FIM.get(st["id"])
                if fn:
                    fn(ctxf, st)
            res["linhas"].append(("Recompensa", f"+${base}", COR_DINHEIRO))
            if sobra:
                res["linhas"].append(("Pontos de sobra", f"+${sobra}", COR_DINHEIRO))
            if juros:
                res["linhas"].append(("Juros", f"+${juros}", COR_DINHEIRO))
            res["linhas"].extend(ctxf["linhas"])
            total = base + sobra + juros + ctxf["dinheiro"]
            res["total"] = total
            self.dinheiro += total
            self.vitorias += 1
            self.etapa += 1
            if self.etapa >= 3:
                self.etapa = 0
                self.nivel += 1
                if self.nivel > NIVEL_FINAL:
                    self.fim = "vitoria"
                else:
                    self.gerar_nivel()
        else:
            perde = APOSTAS[self.aposta][3]
            self.vidas = max(0, self.vidas - perde)
            res["vidas_perdidas"] = perde
            if self.vidas == 0:
                self.fim = "derrota"
        return res

    # ---------- loja ----------
    def _sortear(self, n, excluir):
        pool = [k for k in CURINGAS if k not in excluir]
        out = []
        for _ in range(n):
            if not pool:
                break
            pesos = [RARIDADES[CURINGAS[k]["rar"]][1] for k in pool]
            k = self.rng.choices(pool, weights=pesos)[0]
            pool.remove(k)
            out.append(k)
        return out

    def gerar_loja(self):
        self.oferta = self._sortear(3, {st["id"] for st in self.curingas})
        self.reroll_n = 0
        self.vida_comprada = False

    def custo_reroll(self):
        return 2 + self.reroll_n

    def custo_vida(self):
        return 5 + min(self.nivel, NIVEL_FINAL)

    def reroll(self):
        c = self.custo_reroll()
        if self.dinheiro < c:
            return False, "Dinheiro insuficiente"
        self.dinheiro -= c
        self.reroll_n += 1
        self.oferta = self._sortear(3, {st["id"] for st in self.curingas})
        return True, "Loja renovada"

    def comprar(self, i):
        cid = self.oferta[i]
        if cid is None:
            return False, ""
        d = CURINGAS[cid]
        if len(self.curingas) >= MAX_CURINGAS:
            return False, "Sem espaço: venda um Curinga"
        if self.dinheiro < d["custo"]:
            return False, "Dinheiro insuficiente"
        self.dinheiro -= d["custo"]
        self.curingas.append({"id": cid, "acum": 0.0, "mao": 0.0})
        self.oferta[i] = None
        return True, f"{d['nome']} comprado!"

    def comprar_vida(self):
        c = self.custo_vida()
        if self.vida_comprada:
            return False, ""
        if self.vidas >= MAX_VIDAS:
            return False, "Vidas já estão no máximo"
        if self.dinheiro < c:
            return False, "Dinheiro insuficiente"
        self.dinheiro -= c
        self.vidas += 1
        self.vida_comprada = True
        return True, "+1 vida!"

    def valor_venda(self, i):
        return max(1, CURINGAS[self.curingas[i]["id"]]["custo"] // 2)

    def vender(self, i):
        if not 0 <= i < len(self.curingas):
            return False, ""
        v = self.valor_venda(i)
        nome = CURINGAS[self.curingas[i]["id"]]["nome"]
        self.curingas.pop(i)
        self.dinheiro += v
        return True, f"{nome} vendido por ${v}"


# ============================================================
# 2) UTILIDADES E OBJETOS ANIMADOS
# ============================================================
def limitar(v, a, b):
    return max(a, min(b, v))


class Sprite:
    """
    Uma carta animada. Guarda estado ATUAL (x, y, rot, esc, alpha, face) e o ALVO (a*).
    LERP: a cada frame  atual += (alvo - atual) * k, com k = 1 - (1 - vel)^(dt*60)
    (igual a "vel" a 60 FPS, mas independente do framerate). x, y é o CENTRO da carta.
    face: 0 = verso, 1 = frente (o flip é uma virada em X).
    """

    def __init__(self, carta, x, y):
        self.carta = carta
        self.x, self.y = float(x), float(y)
        self.rot, self.esc, self.alpha, self.face, self.elev = 0.0, 1.0, 255.0, 0.0, 0.0
        self.ax, self.ay = self.x, self.y
        self.arot, self.aesc, self.aalpha, self.aface, self.aelev = 0.0, 1.0, 255.0, 0.0, 0.0
        self.vel = 0.2
        self.atraso = 0.0              # segundos parada antes de começar a se mover (compra escalonada)
        self.zona = "baralho"
        self.ordem = 0                 # para ordenar o desenho (z-order)
        self.visivel = True
        self.brilho = False
        self.brilho_a = 255            # opacidade do brilho (pulsa na dica de 'sua vez')
        self.chegou = False
        self.rot_mesa = random.uniform(-7, 7)

    def dist(self):
        return math.hypot(self.ax - self.x, self.ay - self.y)

    def atualizar(self, dt):
        if self.atraso > 0:
            self.atraso -= dt
            return
        k = 1 - (1 - self.vel) ** (dt * 60)
        kf = 1 - (1 - 0.22) ** (dt * 60)
        self.x += (self.ax - self.x) * k
        self.y += (self.ay - self.y) * k
        self.rot += (self.arot - self.rot) * k
        self.esc += (self.aesc - self.esc) * k
        self.alpha += (self.aalpha - self.alpha) * k
        self.face += (self.aface - self.face) * kf
        self.elev += (self.aelev - self.elev) * kf


class Particula:
    """Faísca neon simples: posição, velocidade, cor e vida."""

    def __init__(self, x, y, vx, vy, cor, vida, tam):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.cor, self.vida, self.vida_max, self.tam = cor, vida, vida, tam

    @property
    def frac(self):
        return max(0.0, self.vida / self.vida_max)

    def atualizar(self, dt):
        self.vida -= dt
        arrasto = 0.93 ** (dt * 60)
        self.vx *= arrasto
        self.vy = self.vy * arrasto + 380 * dt   # gravidade leve
        self.x += self.vx * dt
        self.y += self.vy * dt


class Flutuante:
    """Carta decorativa que vagueia pelo fundo do menu."""

    def __init__(self, carta):
        self.carta = carta
        self.x, self.y = random.uniform(0, LARGURA), random.uniform(0, ALTURA)
        ang, vel = random.uniform(0, math.tau), random.uniform(10, 30)
        self.vx, self.vy = math.cos(ang) * vel, math.sin(ang) * vel
        self.rot, self.vrot = random.uniform(0, 360), random.uniform(-18, 18)
        self.esc = random.uniform(0.55, 1.0)

    def atualizar(self, dt):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.rot += self.vrot * dt
        m = 120
        if self.x < -m:
            self.x = LARGURA + m
        elif self.x > LARGURA + m:
            self.x = -m
        if self.y < -m:
            self.y = ALTURA + m
        elif self.y > ALTURA + m:
            self.y = -m


class Botao:
    """Botão de menu: mesmo esquema de lerp dos sprites (escala, elevação e inclinação)."""

    def __init__(self, chave, rect, rotulo=""):
        self.chave, self.rect, self.rotulo = chave, rect, rotulo
        self.esc, self.elev, self.rot = 1.0, 0.0, 0.0

    def atualizar(self, dt, ativo, t, i):
        k = 1 - (1 - 0.2) ** (dt * 60)
        aesc = 1.07 if ativo else 1.0
        aelev = 12.0 if ativo else 0.0
        arot = math.sin(t * 3 + i) * 1.8 if ativo else math.sin(t * 1.2 + i * 2) * 0.6
        self.esc += (aesc - self.esc) * k
        self.elev += (aelev - self.elev) * k
        self.rot += (arot - self.rot) * k


_TXT = {}


def _render(fonte_, msg, cor):
    """Cache de texto renderizado (renderizar fonte a cada frame é caro).
    Fonte pixel => sem antialiasing, para as bordas ficarem nítidas como no Balatro."""
    k = (id(fonte_), msg, cor)
    img = _TXT.get(k)
    if img is None:
        if len(_TXT) > 500:
            _TXT.clear()
        img = fonte_.render(msg, not FONTE["pixel"], cor)
        _TXT[k] = img
    return img


def texto(tela, fonte_, msg, cor, pos, ancora="center", sombra=True, escala=1.0):
    img = _render(fonte_, msg, cor)
    sh = _render(fonte_, msg, (0, 0, 0)) if sombra else None
    if abs(escala - 1) > 0.01:
        img = pygame.transform.rotozoom(img, 0, escala)
        if sh is not None:
            sh = pygame.transform.rotozoom(sh, 0, escala)
    r = img.get_rect()
    setattr(r, ancora, pos)
    if sh is not None:
        tela.blit(sh, r.move(2, 3))
    tela.blit(img, r)
    return r


def _forma_naipe(surf, naipe, cx, cy, s, cor):
    """Silhueta do naipe (curvas contínuas, sem 'emendas') centrada em (cx, cy), lado ~s."""

    def poli(pontos):
        pygame.draw.polygon(surf, cor, pontos)

    def coracao(sc, dy, inverter):
        pts = []
        for k in range(72):
            a = k * math.tau / 72
            x = 16 * math.sin(a) ** 3
            y = -(13 * math.cos(a) - 5 * math.cos(2 * a) - 2 * math.cos(3 * a) - math.cos(4 * a)) - 2.5
            pts.append((cx + x * sc, cy + dy + (-y if inverter else y) * sc))
        return pts

    def haste(y0, y1, topo, base):
        esq, dire = [], []
        for k in range(9):
            u = k / 8
            w = (topo + (base - topo) * u * u) * s
            y = cy + (y0 + (y1 - y0) * u) * s
            esq.append((cx - w, y))
            dire.append((cx + w, y))
        poli(esq + dire[::-1])

    if naipe == "copas":
        poli(coracao(s * 0.98 / 32, s * 0.02, False))
    elif naipe == "ouros":
        poli([(cx, cy - .5 * s), (cx + .36 * s, cy), (cx, cy + .5 * s), (cx - .36 * s, cy)])
    elif naipe == "espadas":
        poli(coracao(s * 0.86 / 32, -s * 0.13, True))
        haste(0.02, 0.5, .05, .22)
    else:  # paus
        for x, y in ((0, -.22), (-.24, .08), (.24, .08)):
            pygame.draw.circle(surf, cor, (round(cx + x * s), round(cy + y * s)), round(.215 * s))
        pygame.draw.circle(surf, cor, (round(cx), round(cy + .02 * s)), round(.16 * s))
        haste(0.02, 0.5, .045, .21)


_ICONES = {}


def icone_naipe(naipe, tam, cor):
    """Ícone com antialiasing: desenha 4x maior e reduz. Fica em cache por (naipe, tamanho, cor)."""
    tam = max(6, int(round(tam)))
    chave = (naipe, tam, cor)
    ic = _ICONES.get(chave)
    if ic is None:
        ss, lado = 4, int(tam * 1.2) + 2
        grande = pygame.Surface((lado * ss, lado * ss), pygame.SRCALPHA)
        grande.fill((cor[0], cor[1], cor[2], 0))
        _forma_naipe(grande, naipe, lado * ss / 2, lado * ss / 2, tam * ss, cor)
        ic = pygame.transform.smoothscale(grande, (lado, lado))
        _ICONES[chave] = ic
    return ic


def desenhar_naipe(surf, naipe, cx, cy, s, cor, inverter=False):
    ic = icone_naipe(naipe, s, cor)
    if inverter:
        ic = pygame.transform.flip(ic, False, True)
    surf.blit(ic, ic.get_rect(center=(round(cx), round(cy))))


# disposição dos "pips" (símbolos do miolo) das cartas 2..7: (coluna 0..1, linha 0..1)
LAYOUT_PIPS = {
    "2": [(.5, 0), (.5, 1)],
    "3": [(.5, 0), (.5, .5), (.5, 1)],
    "4": [(0, 0), (1, 0), (0, 1), (1, 1)],
    "5": [(0, 0), (1, 0), (.5, .5), (0, 1), (1, 1)],
    "6": [(0, 0), (1, 0), (0, .5), (1, .5), (0, 1), (1, 1)],
    "7": [(0, 0), (1, 0), (.5, .25), (0, .5), (1, .5), (0, 1), (1, 1)],
}


# ============================================================
# 3) VISUAL PROCEDURAL (imagens em cache + fundo simples)
# ============================================================
BW, BH = 110, 72  # resolução baixa do fundo (depois ampliada com suavização = efeito "tinta")


class Visual:
    def __init__(self):
        # fonte(multiplo_da_fonte_pixel, tamanho_da_fonte_padrao_se_faltar_o_arquivo)
        # Ajuste os múltiplos aqui se quiser textos maiores/menores (sempre números inteiros).
        self.f_peq = fonte(1, 24)       # 36 px
        self.f_valor = fonte(2, 38)     # 54 px (canto das cartas)
        self.f_figura = fonte(3, 60)    # 72 px (Q, J, K)
        self.f_med = fonte(1, 34)       # 54 px
        self.f_num = fonte(2, 46)       # 72 px (placar)
        self.f_msg = fonte(2, 40)       # 54 px (mensagens)
        self.f_gde = fonte(4, 84)       # 90 px (títulos)
        self.f_titulo = fonte(9, 190)  # 216 px (BISCA)
        if not FONTE["pixel"]:
            print("[aviso] fonte do Balatro não encontrada em 'fontes/m6x11plus.ttf'; usando a fonte padrão.")
        self._faces = {}
        self._brilhos = {}
        self._letras = {}
        self.verso = self._criar_verso().convert_alpha()
        self.sombra = self._criar_sombra().convert_alpha()
        self.contorno = self._criar_contorno().convert_alpha()
        self.vinheta = self._criar_vinheta(True).convert_alpha()
        self.vinheta_menu = self._criar_vinheta(False).convert_alpha()
        self.veu_escuro = pygame.Surface((LARGURA, ALTURA), pygame.SRCALPHA)
        self.veu_escuro.fill((0, 0, 0, 170))
        self.veu_escuro = self.veu_escuro.convert_alpha()
        self.veu_tip = pygame.Surface((LARGURA, ALTURA), pygame.SRCALPHA)
        self.veu_tip.fill((0, 0, 0, 125))
        self.veu_tip = self.veu_tip.convert_alpha()
        self._curingas = {}
        self.fundo_peq = pygame.Surface((BW, BH))
        self._grande = None
        self._comp = {}
        self._t_fundo = -1.0

    def _txt(self, fonte_, msg, cor):
        return fonte_.render(msg, not FONTE["pixel"], cor)

    # ---------- cartas ----------
    def face(self, c):
        if c not in self._faces:
            self._faces[c] = self._criar_face(c).convert_alpha()
        return self._faces[c]

    def _criar_face(self, c):
        s = pygame.Surface((CARTA_L, CARTA_A), pygame.SRCALPHA)
        rect = s.get_rect()
        cor = COR_NAIPE[c.naipe]
        pygame.draw.rect(s, (247, 242, 231), rect, border_radius=10)
        pygame.draw.rect(s, (226, 218, 202), rect.inflate(-10, -10), 1, border_radius=7)  # filete interno
        # cantos: valor + naipe, ambos na cor do naipe
        canto = pygame.Surface((30, 62), pygame.SRCALPHA)
        t = self._txt(self.f_valor, c.valor, cor)
        canto.blit(t, (15 - t.get_width() // 2, 0))
        desenhar_naipe(canto, c.naipe, 15, 47, 17, cor)
        s.blit(canto, (4, 3))
        s.blit(pygame.transform.rotate(canto, 180), (CARTA_L - 34, CARTA_A - 65))
        # miolo
        if c.valor == "A":
            desenhar_naipe(s, c.naipe, 50, 73, 58, cor)
        elif c.valor in LAYOUT_PIPS:
            for fx, fy in LAYOUT_PIPS[c.valor]:
                desenhar_naipe(s, c.naipe, 39 + fx * 22, 30 + fy * 86, 20, cor, inverter=fy > .5)
        else:
            self._miolo_figura(s, c, cor)
        pygame.draw.rect(s, (30, 25, 45), rect, 3, border_radius=10)
        return s

    def _miolo_figura(self, s, c, cor):
        """Q, J, K: painel com duas tonalidades do naipe, letra grande e coroa."""
        claro = tuple(int(255 - (255 - ch) * 0.22) for ch in cor)
        medio = tuple(int(255 - (255 - ch) * 0.42) for ch in cor)
        painel = pygame.Rect(33, 24, 34, 98)
        pygame.draw.rect(s, claro, painel)
        pygame.draw.polygon(s, medio, [(painel.right - 1, painel.y + 1), (painel.right - 1, painel.bottom - 1),
                                       (painel.x + 1, painel.bottom - 1)])
        pygame.draw.rect(s, cor, painel, 2)
        t = self._txt(self.f_figura, c.valor, cor)
        s.blit(t, t.get_rect(center=(50, 75)))
        if c.valor == "J":
            desenhar_naipe(s, c.naipe, 50, 40, 16, cor)
        else:
            self._coroa(s, 50, 48, 24, cor, perolas=(c.valor == "Q"))
        desenhar_naipe(s, c.naipe, 50, 108, 16, cor, inverter=True)

    @staticmethod
    def _coroa(s, cx, base, w, cor, perolas):
        h = w * 0.72
        pygame.draw.polygon(s, cor, [(cx - w / 2, base), (cx - w / 2, base - h * .6), (cx - w / 4, base - h * .3),
                                     (cx, base - h * .85), (cx + w / 4, base - h * .3),
                                     (cx + w / 2, base - h * .6), (cx + w / 2, base)])
        if perolas:
            for x, y in ((cx - w / 2, base - h * .6), (cx, base - h * .85), (cx + w / 2, base - h * .6)):
                pygame.draw.circle(s, cor, (round(x), round(y) - 1), 2)

    def _criar_verso(self):
        s = pygame.Surface((CARTA_L, CARTA_A), pygame.SRCALPHA)
        rect = s.get_rect()
        pygame.draw.rect(s, (245, 240, 235), rect, border_radius=10)
        interno = rect.inflate(-12, -12)
        pygame.draw.rect(s, (120, 22, 48), interno, border_radius=6)
        s.set_clip(interno.inflate(-6, -6))
        for k in range(-CARTA_A, CARTA_L + CARTA_A, 14):
            pygame.draw.line(s, (225, 70, 100), (k, 0), (k + CARTA_A, CARTA_A), 2)
            pygame.draw.line(s, (225, 70, 100), (k + CARTA_A, 0), (k, CARTA_A), 2)
        s.set_clip(None)
        pygame.draw.circle(s, (245, 240, 235), rect.center, 17)
        pygame.draw.circle(s, (120, 22, 48), rect.center, 12)
        desenhar_naipe(s, "ouros", rect.centerx, rect.centery, 14, DOURADO)
        pygame.draw.rect(s, (30, 25, 45), rect, 3, border_radius=10)
        return s

    def _criar_sombra(self):
        s = pygame.Surface((CARTA_L, CARTA_A), pygame.SRCALPHA)
        pygame.draw.rect(s, (0, 0, 0, 110), s.get_rect(), border_radius=10)
        return s

    def _criar_contorno(self):
        """Brilho dourado suave que aparece atrás da carta em hover / vencedora."""
        s = pygame.Surface((CARTA_L + 24, CARTA_A + 24), pygame.SRCALPHA)
        for k in range(6):
            r = s.get_rect().inflate(-k * 4, -k * 4)
            pygame.draw.rect(s, (255, 225, 110, 25 + k * 22), r, border_radius=18 - k)
        return s

    def _criar_vinheta(self, com_mesa):
        s = pygame.Surface((LARGURA, ALTURA), pygame.SRCALPHA)
        if com_mesa:
            mesa = pygame.Rect(120, 130, LARGURA - 240, ALTURA - 260)
            pygame.draw.ellipse(s, (0, 0, 0, 70), mesa)
            pygame.draw.ellipse(s, (255, 255, 255, 28), mesa, 3)
        for i in range(0, 130, 3):
            a = int(190 * (1 - i / 130) ** 2)
            pygame.draw.rect(s, (0, 0, 0, a), (i, i, LARGURA - 2 * i, ALTURA - 2 * i), 3)
        return s

    def letra(self, ch, cor):
        """Letra do título com contorno preto grosso e sombra projetada (cache)."""
        k = (ch, cor)
        if k not in self._letras:
            img = self._txt(self.f_titulo, ch, cor)
            sh = self._txt(self.f_titulo, ch, (0, 0, 0))
            pad = 10
            w, h = img.get_size()
            s = pygame.Surface((w + pad * 2, h + pad * 2 + 8), pygame.SRCALPHA)
            for dx, dy in ((-5, 0), (5, 0), (0, -5), (0, 5), (-4, -4), (4, -4), (-4, 4), (4, 4)):
                s.blit(sh, (pad + dx, pad + dy))
            s.blit(sh, (pad + 3, pad + 9))
            s.blit(img, (pad, pad))
            self._letras[k] = s.convert_alpha()
        return self._letras[k]

    # ---------- brilho (glow) para partículas, usado com blend aditivo ----------
    def brilho(self, cor, raio):
        chave = (cor, raio)
        s = self._brilhos.get(chave)
        if s is None:
            s = pygame.Surface((raio * 2 + 1, raio * 2 + 1))
            for r in range(raio, 0, -1):
                k = (1 - r / raio) ** 1.6
                pygame.draw.circle(s, (int(cor[0] * k), int(cor[1] * k), int(cor[2] * k)), (raio, raio), r)
            s = s.convert()
            self._brilhos[chave] = s
        return s

    # ---------- fundo (espiral lenta em dois tons) + vinheta, fundidos e em cache ----------
    def fundo(self, t, menu=False):
        """Recalcula a espiral a 20 fps e já funde a vinheta: 1 único blit por frame."""
        if self._grande is None or t - self._t_fundo >= 1 / 20:
            self._renderizar_fundo(t)
            self._grande = pygame.transform.smoothscale(self.fundo_peq, (LARGURA, ALTURA))
            self._t_fundo = t
            self._comp = {}
        if menu not in self._comp:
            s = self._grande.copy()
            s.blit(self.vinheta_menu if menu else self.vinheta, (0, 0))
            self._comp[menu] = s
        return self._comp[menu]

    def _renderizar_fundo(self, t):
        s = self.fundo_peq
        s.fill(FUNDO_BASE)
        cx, cy = BW / 2, BH / 2
        rs = [80 * k / 14 for k in range(15)]
        for a in range(6):
            ang0 = a * math.tau / 6 + t * 0.12
            ext, interno = [], []
            for r in rs:
                ang = ang0 + r * 0.06 + 0.3 * math.sin(t * 0.4 + r * 0.08)
                ext.append((cx + math.cos(ang) * r, cy + math.sin(ang) * r))
                interno.append((cx + math.cos(ang + math.pi / 6) * r, cy + math.sin(ang + math.pi / 6) * r))
            pygame.draw.polygon(s, FUNDO_BRACO, ext + interno[::-1])

    # ---------- cartas de Curinga (Modo Aposta) ----------
    def curinga(self, cid):
        """Carta de Curinga 156x230, desenhada uma vez e guardada em cache."""
        s = self._curingas.get(cid)
        if s is None:
            s = self._criar_curinga(cid).convert_alpha()
            self._curingas[cid] = s
        return s

    def _criar_curinga(self, cid):
        d = CURINGAS[cid]
        W, H = 156, 230
        s = pygame.Surface((W, H), pygame.SRCALPHA)
        rect = s.get_rect()
        cor_r = RARIDADES[d["rar"]][0]
        escura = tuple(int(c * 0.55) for c in cor_r)
        pygame.draw.rect(s, (247, 242, 231), rect, border_radius=12)
        pygame.draw.rect(s, cor_r, pygame.Rect(0, 0, W, 10), border_top_left_radius=12, border_top_right_radius=12)
        pygame.draw.rect(s, cor_r, rect.inflate(-10, -10), 2, border_radius=8)
        ls = self.f_peq.get_linesize()
        y = 18
        for ln in quebrar(self.f_peq, d["nome"], W - 24)[:2]:
            t = self._txt(self.f_peq, ln, (30, 25, 45))
            s.blit(t, t.get_rect(midtop=(W // 2, y)))
            y += ls
        # arte: medalhão com o naipe e "faíscas" sorteadas a partir do id (sempre iguais para o mesmo Curinga)
        rnd = random.Random(cid)
        cy = 140
        claro = tuple(int(255 - (255 - c) * 0.35) for c in cor_r)
        pygame.draw.circle(s, claro, (W // 2, cy), 50)
        pygame.draw.circle(s, cor_r, (W // 2, cy), 50, 3)
        for _ in range(12):
            ang = rnd.uniform(0, math.tau)
            r = rnd.uniform(56, 70)
            x, yy = W // 2 + math.cos(ang) * r, cy + math.sin(ang) * r * 0.85
            k = rnd.choice((3, 4, 5))
            pygame.draw.polygon(s, cor_r, [(x, yy - k), (x + k, yy), (x, yy + k), (x - k, yy)])
        desenhar_naipe(s, d["naipe"], W // 2, cy, 60, COR_NAIPE[d["naipe"]])
        t = self._txt(self.f_peq, d["rar"].upper(), escura)
        s.blit(t, t.get_rect(midbottom=(W // 2, H - 12)))
        pygame.draw.rect(s, (30, 25, 45), rect, 3, border_radius=12)
        return s

    # ---------- UI ----------
    @staticmethod
    def painel(tela, rect, cor_borda, preench=(28, 24, 48)):
        pygame.draw.rect(tela, (0, 0, 0), rect.move(0, 6), border_radius=14)
        pygame.draw.rect(tela, preench, rect, border_radius=14)
        pygame.draw.rect(tela, cor_borda, rect, 4, border_radius=14)


# ============================================================
# 4) APLICAÇÃO / INTERFACE
# ============================================================
class App:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Bisca")
        try:
            self.janela = pygame.display.set_mode((LARGURA, ALTURA), pygame.SCALED, vsync=1)
        except pygame.error:
            self.janela = pygame.display.set_mode((LARGURA, ALTURA))
        self.tela = pygame.Surface((LARGURA, ALTURA)).convert()  # "canvas": permite tremer a tela inteira
        self.relogio = pygame.time.Clock()
        self.vis = Visual()
        self.veu = pygame.Surface((LARGURA, ALTURA)).convert()   # cortina preta das transições
        self.veu.fill((0, 0, 0))
        self.t = 0.0
        self.particulas = []
        self.tremor = 0.0
        self.cortina, self.cortina_alvo = 255.0, 0.0   # começa em preto e "abre"
        self.modo = "1x1"
        self.cfg = MODOS[self.modo]
        # rede
        self.papel = None            # None | "host" | "cliente"
        self.sala = None             # SalaHost
        self.entrada = None          # EntradaCliente
        self.online = False
        self.assento = 0             # meu assento global
        self.fila_rede = []          # jogadas recebidas esperando a vez: (idx_local, carta, origem)
        self.ip_txt = ""
        self.menu_aviso, self.menu_aviso_ate = "", 0
        self.mp_msg = ""
        self.aviso_txt, self.aviso_ate = "", 0
        self.save = carregar_save()
        self.dicas = "vaza1" not in self.save["vistas"]   # tutorial feito => HUD só com sinais visuais
        self.tip_atual = None
        self.textos = []
        self.run = None
        self.confirma_ate = 0
        self.perfil = None
        self.rg_conf, self.rg_meta, self.rg_res, self.rg_meta_ok = None, 0, None, False
        self.exib_score = 0.0
        self.pulso_cur = [0.0] * MAX_CURINGAS
        self.aposta_sel = 0
        self.loja_sel = 0
        self.loja_msg = ("", BRANCO, 0)
        self.iniciar_menu()

    @staticmethod
    def sair():
        pygame.quit()
        sys.exit()

    # ============================================================
    # REDE: ciclo de vida
    # ============================================================
    def encerrar_rede(self):
        if self.sala:
            self.sala.fechar()
        if self.entrada:
            self.entrada.fechar()
        self.sala = self.entrada = None
        self.papel = None
        self.online = False
        self.fila_rede = []

    def sair_da_sala(self, msg=""):
        self.voltar_ao_menu()
        if msg:
            self.menu_aviso = msg
            self.menu_aviso_ate = pygame.time.get_ticks() + 5000

    # ============================================================
    # MENU PRINCIPAL
    # ============================================================
    def iniciar_menu(self):
        pygame.display.set_caption("Bisca")
        self.cena = "menu"
        self.sel = 0
        self.run = None                 # sair para o menu abandona qualquer run
        self.pendente = None            # (acao, momento) aguardando a animação do clique
        modo_r = lambda cx, cy: pygame.Rect(cx - 170, cy - 115, 340, 230)
        peq_r = lambda cx: pygame.Rect(cx - 115, CY + 215 - 29, 230, 58)
        self.botoes = [Botao("1x1", modo_r(CX - 190, CY + 40)),
                       Botao("2x2", modo_r(CX + 190, CY + 40)),
                       Botao("aposta", peq_r(CX - 250), "MODO APOSTA"),
                       Botao("mp", peq_r(CX), "MULTIPLAYER"),
                       Botao("sair", peq_r(CX + 250), "SAIR")]
        if not hasattr(self, "flutuantes"):
            todas = [Carta(n, v) for n in NAIPES for v in VALORES]
            self.flutuantes = [Flutuante(random.choice(todas)) for _ in range(16)]

    def voltar_ao_menu(self):
        self.encerrar_rede()
        self.tip_atual = None
        self.textos = []
        self.particulas = []
        self.iniciar_menu()
        self.cortina, self.cortina_alvo = 255.0, 0.0

    def selecionar(self, i):
        if i == self.sel:
            return
        self.sel = i
        b = self.botoes[i]
        b.rot += random.choice((-5, 5))      # "chacoalhada" ao entrar, igual ao hover das cartas
        b.esc = 1.12

    def navegar(self, dx, dy):
        linhas = [[0, 1], [2, 3, 4]]
        lin = 0 if self.sel < 2 else 1
        col = linhas[lin].index(self.sel)
        if dx:
            col = int(limitar(col + dx, 0, len(linhas[lin]) - 1))
        if dy:
            nova = int(limitar(lin + dy, 0, 1))
            if nova != lin:
                lin = nova
                col = min(col, len(linhas[lin]) - 1)
        self.selecionar(linhas[lin][col])

    def ativar(self, i):
        if self.pendente:
            return
        b = self.botoes[i]
        if b.chave == "mp":
            self.iniciar_mp()
            return
        if b.chave == "aposta":
            self.iniciar_run()
            return
        b.esc = 1.2
        if b.chave != "sair":
            self.explodir(random.choice(NAIPES), 70, *b.rect.center)
            self.tremor = max(self.tremor, 6.0)
        self.pendente = (b.chave, pygame.time.get_ticks() + 450)
        self.cortina_alvo = 255.0

    def evento_menu(self, e):
        if self.pendente:
            return
        if e.type == pygame.MOUSEMOTION:
            for i, b in enumerate(self.botoes):
                if b.rect.collidepoint(e.pos):
                    self.selecionar(i)
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            for i, b in enumerate(self.botoes):
                if b.rect.collidepoint(e.pos):
                    self.selecionar(i)
                    self.ativar(i)
        elif e.type == pygame.KEYDOWN:
            k = e.key
            if k == pygame.K_ESCAPE:
                self.sair()
            elif k in (pygame.K_LEFT, pygame.K_a):
                self.navegar(-1, 0)
            elif k in (pygame.K_RIGHT, pygame.K_d):
                self.navegar(1, 0)
            elif k in (pygame.K_UP, pygame.K_w):
                self.navegar(0, -1)
            elif k in (pygame.K_DOWN, pygame.K_s):
                self.navegar(0, 1)
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self.ativar(self.sel)
            elif k == pygame.K_t:
                self.refazer_tutorial()
            elif k in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4):
                i = {pygame.K_1: 0, pygame.K_2: 1, pygame.K_3: 2, pygame.K_4: 3}[k]
                self.selecionar(i)
                self.ativar(i)

    def atualizar_menu(self, dt):
        for f in self.flutuantes:
            f.atualizar(dt)
        for i, b in enumerate(self.botoes):
            b.atualizar(dt, i == self.sel, self.t, i)
        if self.pendente and pygame.time.get_ticks() >= self.pendente[1]:
            acao = self.pendente[0]
            self.pendente = None
            if acao == "sair":
                self.sair()
            self.nova_partida(acao)
            self.cena = "jogo"
            self.cortina, self.cortina_alvo = 255.0, 0.0

    def desenhar_flutuantes(self):
        v = self.vis
        for f in self.flutuantes:
            img = pygame.transform.rotozoom(v.face(f.carta), f.rot, f.esc)
            img.set_alpha(110)
            self.tela.blit(img, img.get_rect(center=(f.x, f.y)))

    def desenhar_titulo(self):
        t, v = self.tela, self.vis
        palavra = "BISCA"
        esp = 8
        larguras = [v.f_titulo.size(c)[0] for c in palavra]
        x = CX - (sum(larguras) + esp * (len(palavra) - 1)) / 2
        for i, c in enumerate(palavra):
            cx = x + larguras[i] / 2
            y = 120 + math.sin(self.t * 2.2 + i * 0.8) * 9
            rot = math.sin(self.t * 1.6 + i * 1.3) * 5
            esc = 1 + 0.04 * math.sin(self.t * 3 + i)
            img = pygame.transform.rotozoom(v.letra(c, CORES_TITULO[i % len(CORES_TITULO)]), rot, esc)
            t.blit(img, img.get_rect(center=(cx, y)))
            x += larguras[i] + esp
        texto(t, v.f_med, "ESCOLHA O MODO DE JOGO", BRANCO, (CX, 232 + math.sin(self.t * 2.5) * 2))

    def desenhar_botao(self, b, ativo):
        v = self.vis
        w, h = b.rect.size
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        r = pygame.Rect(6, 6, w - 12, h - 20)
        v.painel(s, r, DOURADO if ativo else (120, 110, 170), (40, 34, 66) if ativo else (28, 24, 48))
        if b.chave in MODOS:
            dupla = b.chave == "2x2"
            texto(s, v.f_gde, "2 x 2" if dupla else "1 x 1", DOURADO if ativo else BRANCO, (r.centerx, r.y + 50))
            texto(s, v.f_peq, "Em dupla contra 2 CPUs" if dupla else "Você contra a CPU",
                  BRANCO, (r.centerx, r.y + 106))
            texto(s, v.f_peq, "Jogo em duplas" if dupla else "Duelo rápido", (190, 190, 215),
                  (r.centerx, r.y + 132))
            # bolinhas: azul = sua equipe, vermelho = rival
            por_lado = 2 if dupla else 1
            y = r.bottom - 30
            for x in [r.centerx - 30 - k * 30 for k in range(por_lado)]:
                pygame.draw.circle(s, (245, 245, 240), (x, y), 14)
                pygame.draw.circle(s, AZUL_EQ, (x, y), 10)
            for x in [r.centerx + 30 + k * 30 for k in range(por_lado)]:
                pygame.draw.circle(s, (245, 245, 240), (x, y), 14)
                pygame.draw.circle(s, VERMELHO_EQ, (x, y), 10)
            texto(s, v.f_peq, "x", BRANCO, (r.centerx, y))
        else:
            texto(s, v.f_med, b.rotulo, DOURADO if ativo else BRANCO, r.center)
        if abs(b.rot) > 0.1 or abs(b.esc - 1) > 0.005:
            s = pygame.transform.rotozoom(s, b.rot, b.esc)
        self.tela.blit(s, s.get_rect(center=(b.rect.centerx, b.rect.centery - b.elev)))

    def desenhar_menu(self):
        t, v = self.tela, self.vis
        t.blit(v.fundo(self.t, True), (0, 0))
        self.desenhar_flutuantes()
        self.desenhar_titulo()
        for i, b in enumerate(self.botoes):
            self.desenhar_botao(b, i == self.sel)
        self.desenhar_particulas()
        if self.menu_aviso and pygame.time.get_ticks() < self.menu_aviso_ate:
            texto(t, v.f_peq, self.menu_aviso, VERMELHO_EQ, (CX, ALTURA - 56))
        elif self.save["melhor_nivel"]:
            texto(t, v.f_peq, f"Melhor run: nível {self.save['melhor_nivel']}   |   Runs: {self.save['runs']}",
                  DOURADO, (CX, ALTURA - 56))
        texto(t, v.f_peq, "Setas/mouse: escolher   ENTER: confirmar   1-4: atalhos   T: tutorial   ESC: sair",
              (190, 190, 215), (CX, ALTURA - 22))

    # ============================================================
    # MENU MULTIPLAYER
    # ============================================================
    def iniciar_mp(self):
        self.cena = "mp"
        self.mp_sub = "inicio"       # inicio | ip | conectando | host_lobby | cli_lobby
        self.mp_sel = 0
        self.mp_msg = ""
        itens = [("host1x1", "Criar sala 1x1"), ("host2x2", "Criar sala 2x2"),
                 ("entrar", "Entrar em uma sala"), ("voltar", "Voltar")]
        self.mp_botoes = [Botao(ch, pygame.Rect(CX - 210, 262 + i * 84, 420, 64), rot)
                          for i, (ch, rot) in enumerate(itens)]

    def mp_voltar(self):
        if self.mp_sub == "inicio":
            self.iniciar_menu()
        else:
            self.encerrar_rede()
            self.mp_sub = "inicio"
            self.mp_msg = ""

    def mp_ativar(self, i):
        ch = self.mp_botoes[i].chave
        self.mp_botoes[i].esc = 1.2
        if ch in ("host1x1", "host2x2"):
            modo = ch[-3:]
            try:
                self.sala = SalaHost(modo)
            except OSError:
                self.mp_msg = f"Não foi possível abrir a porta {PORTA} (já em uso?)"
                return
            self.papel = "host"
            self.modo = modo
            self.mp_sub = "host_lobby"
            self.mp_msg = ""
        elif ch == "entrar":
            self.mp_sub = "ip"
            self.mp_msg = ""
        else:
            self.iniciar_menu()

    def mp_conectar(self):
        destino = self.ip_txt.strip() or "127.0.0.1"
        self.entrada = EntradaCliente(destino)
        self.papel = "cliente"
        self.mp_sub = "conectando"
        self.mp_msg = ""

    def evento_mp(self, e):
        if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
            self.mp_voltar()
            return
        sub = self.mp_sub
        if sub == "inicio":
            if e.type == pygame.MOUSEMOTION:
                for i, b in enumerate(self.mp_botoes):
                    if b.rect.collidepoint(e.pos):
                        self.mp_sel = i
            elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                for i, b in enumerate(self.mp_botoes):
                    if b.rect.collidepoint(e.pos):
                        self.mp_sel = i
                        self.mp_ativar(i)
            elif e.type == pygame.KEYDOWN:
                if e.key in (pygame.K_UP, pygame.K_w):
                    self.mp_sel = (self.mp_sel - 1) % len(self.mp_botoes)
                elif e.key in (pygame.K_DOWN, pygame.K_s):
                    self.mp_sel = (self.mp_sel + 1) % len(self.mp_botoes)
                elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                    self.mp_ativar(self.mp_sel)
        elif sub == "ip":
            if e.type == pygame.KEYDOWN:
                if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    self.mp_conectar()
                elif e.key == pygame.K_BACKSPACE:
                    self.ip_txt = self.ip_txt[:-1]
                elif len(e.unicode) == 1 and e.unicode in "0123456789.:-abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ":
                    if len(self.ip_txt) < 40:
                        self.ip_txt += e.unicode
        elif sub == "host_lobby":
            if e.type == pygame.KEYDOWN and e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self.sala.conexoes:
                    self.iniciar_online_host()
                else:
                    self.mp_msg = "Aguarde pelo menos 1 jogador entrar na sala"

    def atualizar_mp(self, dt):
        for f in self.flutuantes:
            f.atualizar(dt)
        for i, b in enumerate(self.mp_botoes):
            b.atualizar(dt, self.mp_sub == "inicio" and i == self.mp_sel, self.t, i)

    # ---------- desenho do multiplayer ----------
    def _linha_assento(self, y, x0, i, nome, estado, cor_estado, equipe):
        t, v = self.tela, self.vis
        pygame.draw.circle(t, (245, 245, 240), (x0, y), 12)
        pygame.draw.circle(t, AZUL_EQ if equipe == 0 else VERMELHO_EQ, (x0, y), 8)
        texto(t, v.f_peq, f"{i + 1}. {nome}", BRANCO, (x0 + 24, y), "midleft")
        texto(t, v.f_peq, estado, cor_estado, (x0 + 500, y), "midright")

    def _lista_assentos(self, modo, conectados, meu, y0):
        cfg = MODOS[modo]
        pontos = "." * (int(self.t * 2) % 4)
        for i in range(len(cfg["nomes"])):
            y = y0 + i * 40
            if i == 0:
                nome, est, cor = ("Host" if meu != 0 else "Você (host)"), "pronto", VERDE
            elif i in conectados:
                nome, est, cor = ("Você" if i == meu else f"Jogador {i + 1}"), "conectado", VERDE
            else:
                nome, est, cor = "vaga livre (vira CPU)", "aguardando" + pontos, CINZA
            self._linha_assento(y, CX - 250, i, nome, est, cor, cfg["equipes"][i])

    def desenhar_mp(self):
        t, v = self.tela, self.vis
        t.blit(v.fundo(self.t, True), (0, 0))
        self.desenhar_flutuantes()
        texto(t, v.f_gde, "MULTIPLAYER", DOURADO, (CX, 110 + math.sin(self.t * 2) * 5))
        sub = self.mp_sub
        if sub == "inicio":
            for i, b in enumerate(self.mp_botoes):
                self.desenhar_botao(b, i == self.mp_sel)
            dica = "Todos precisam estar na mesma rede (ou VPN). Porta " + str(PORTA)
        elif sub == "ip":
            r = pygame.Rect(CX - 280, 230, 560, 230)
            v.painel(t, r, DOURADO)
            texto(t, v.f_med, "IP do host", BRANCO, (CX, r.y + 40))
            caixa = pygame.Rect(0, 0, 480, 56)
            caixa.center = (CX, r.y + 108)
            pygame.draw.rect(t, (10, 8, 20), caixa, border_radius=8)
            pygame.draw.rect(t, (120, 110, 170), caixa, 3, border_radius=8)
            cursor = "_" if int(self.t * 2) % 2 == 0 else " "
            texto(t, v.f_med, self.ip_txt + cursor, BRANCO, (caixa.x + 14, caixa.centery), "midleft", sombra=False)
            texto(t, v.f_peq, "Ex.: 192.168.0.12   ou   192.168.0.12:5555", CINZA, (CX, r.y + 170))
            dica = "ENTER: conectar   |   ESC: voltar"
        elif sub == "conectando":
            r = pygame.Rect(CX - 280, 260, 560, 150)
            v.painel(t, r, DOURADO)
            e = self.entrada
            texto(t, v.f_med, "Conectando" + "." * (int(self.t * 3) % 4), BRANCO, (CX, r.y + 55))
            texto(t, v.f_peq, f"{e.host}:{e.porta}" if e else "", CINZA, (CX, r.y + 108))
            dica = "ESC: cancelar"
        elif sub == "host_lobby":
            r = pygame.Rect(CX - 320, 190, 640, 380)
            v.painel(t, r, DOURADO)
            texto(t, v.f_med, f"SALA {self.sala.modo}", BRANCO, (CX, r.y + 38))
            texto(t, v.f_peq, f"Seu IP: {self.sala.ip}     Porta: {self.sala.servidor.porta}",
                  DOURADO, (CX, r.y + 88))
            self._lista_assentos(self.sala.modo, self.sala.conexoes, 0, r.y + 142)
            texto(t, v.f_peq, "Passe o IP acima para os amigos entrarem", CINZA, (CX, r.bottom - 34))
            dica = "ENTER: iniciar (vagas vazias viram CPU)   |   ESC: fechar a sala"
        else:  # cli_lobby
            e = self.entrada
            modo = e.modo if e.modo in MODOS else "1x1"
            r = pygame.Rect(CX - 320, 190, 640, 380)
            v.painel(t, r, DOURADO)
            texto(t, v.f_med, f"SALA {modo}", BRANCO, (CX, r.y + 38))
            meu = e.assento if e.assento is not None else -1
            texto(t, v.f_peq, f"Você é o assento {meu + 1}" if meu >= 0 else "Entrando...", DOURADO,
                  (CX, r.y + 88))
            self._lista_assentos(modo, e.conectados, meu, r.y + 142)
            texto(t, v.f_peq, "Aguardando o host iniciar" + "." * (int(self.t * 2) % 4), CINZA,
                  (CX, r.bottom - 34))
            dica = "ESC: sair da sala"
        if self.mp_msg:
            texto(t, v.f_peq, self.mp_msg, VERMELHO_EQ, (CX, ALTURA - 58))
        texto(t, v.f_peq, dica, (190, 190, 215), (CX, ALTURA - 22))

    # ============================================================
    # REDE: durante o lobby e durante o jogo
    # ============================================================
    def processar_rede(self):
        if self.papel == "host":
            for a, msg in self.sala.atualizar():
                if self.cena != "jogo":
                    continue
                t = msg.get("t")
                if t == "jogada":
                    c = carta_de(msg.get("carta"))
                    if c is not None and msg.get("assento") == a:
                        self.fila_rede.append(((a - self.assento) % self.mao.n, c, a))
                elif t == "saiu":
                    self.cliente_saiu(a)
        elif self.papel == "cliente":
            self.processar_cliente()

    def processar_cliente(self):
        ent = self.entrada
        if ent.estado == "erro":
            self.mp_msg = ent.erro
            self.encerrar_rede()
            self.mp_sub = "ip"
            return
        if ent.estado != "ok":
            return
        if self.cena == "mp" and self.mp_sub == "conectando":
            self.mp_sub = "cli_lobby"
        for msg in ent.conn.receber():
            t = msg.get("t")
            if t == "bemvindo":
                ent.assento = msg.get("assento")
                ent.modo = msg.get("modo")
            elif t == "lobby":
                ent.conectados = list(msg.get("conectados", []))
            elif t == "inicio":
                self.iniciar_online_cliente(msg)
            elif t == "jogada" and self.cena == "jogo":
                c = carta_de(msg.get("carta"))
                g = msg.get("assento")
                if c is not None and isinstance(g, int):
                    self.fila_rede.append(((g - self.assento) % self.mao.n, c, None))
            elif t == "recusado":
                self.sair_da_sala(str(msg.get("motivo", "Entrada recusada")))
                return
            elif t == "desconectou":
                self.sair_da_sala("A conexão com o host foi encerrada")
                return

    def iniciar_online_host(self):
        """Embaralha, manda o baralho a todos e começa (também usado para reiniciar)."""
        deck = novo_baralho()
        self.sala.iniciar(deck)
        self.fila_rede = []
        self.nova_partida(self.sala.modo, online={"k": 0, "humanos": self.sala.humanos(), "deck": deck})
        if self.cena != "jogo":
            self.cena = "jogo"
            self.cortina, self.cortina_alvo = 255.0, 0.0

    def iniciar_online_cliente(self, msg):
        modo, k = msg.get("modo"), msg.get("assento")
        deck = [carta_de(x) for x in msg.get("baralho", [])]
        humanos = msg.get("humanos", [])
        if (modo not in MODOS or not isinstance(k, int) or not 0 <= k < len(MODOS[modo]["nomes"])
                or None in deck or len(set(deck)) != 40 or not isinstance(humanos, list)):
            return
        self.fila_rede = []
        self.nova_partida(modo, online={"k": k, "humanos": humanos, "deck": deck})
        if self.cena != "jogo":
            self.cena = "jogo"
            self.cortina, self.cortina_alvo = 255.0, 0.0

    def cliente_saiu(self, a):
        """Um cliente caiu durante a partida: a CPU do host assume o lugar dele."""
        p = self.mao
        idx = (a - self.assento) % p.n
        j = p.jogadores[idx]
        j.tipo = "cpu"
        self.avisar(f"{j.nome} saiu: a CPU assumiu")
        if self.estado == "remoto" and p.vez == idx:
            self.estado = "cpu"
            self.evento_em = pygame.time.get_ticks() + ATRASO_CPU

    def enviar_jogada(self, idx, carta):
        """Avisa a rede que o jogador local idx jogou a carta."""
        if not self.online:
            return
        msg = {"t": "jogada", "assento": (idx + self.assento) % self.mao.n, "carta": carta_json(carta)}
        if self.papel == "host":
            self.sala.transmitir(msg)
        elif self.papel == "cliente" and self.entrada.conn:
            self.entrada.conn.enviar(msg)

    def consumir_jogada_remota(self):
        """No estado 'remoto', aplica a próxima jogada recebida que seja da vez de quem está esperando."""
        p = self.mao
        while self.fila_rede and self.estado == "remoto":
            idx, carta, origem = self.fila_rede.pop(0)
            if idx != p.vez or carta not in p.jogadores[idx].mao:
                continue                                   # inválida ou fora de hora: descarta
            p.jogar(idx, carta)
            if self.papel == "host" and origem is not None:   # o host repassa aos demais clientes
                self.sala.transmitir({"t": "jogada", "assento": (idx + self.assento) % p.n,
                                      "carta": carta_json(carta)}, exceto=origem)
            self.apos_jogada()

    # ============================================================
    # JOGO
    # ============================================================
    @property
    def mao(self):
        return self.partida

    def nova_partida(self, modo=None, online=None):
        if modo:
            self.modo = modo
        cfg = dict(MODOS[self.modo])
        self.online = online is not None
        self.perfil = None
        if online is None:
            jogadores = [Jogador(nome, eq, "humano" if i == 0 else "cpu")
                         for i, (nome, eq) in enumerate(zip(cfg["nomes"], cfg["equipes"]))]
            if self.run:                                    # Modo Aposta: rival procedural + regra do confronto
                conf = self.run.confronto
                jogadores[1].nome = conf.oponente.nome
                self.perfil = PERFIS[conf.oponente.perfil]
                self.partida = Partida(jogadores, regras=self.run.regras_partida())
            else:
                self.partida = Partida(jogadores)
            self.assento = 0
            ordem = list(range(self.partida.n))
            pygame.display.set_caption("Bisca - Modo Aposta" if self.run else cfg["titulo"])
        else:
            k = online["k"]
            self.partida = montar_partida_online(self.modo, k, online["humanos"], online["deck"],
                                                 host=(self.papel == "host"))
            self.assento = k
            n = self.partida.n
            ordem = [(g - k) % n for g in range(n)]     # ordem de distribuição, em índices locais
            if self.modo == "1x1":
                cfg["placar"] = ("VOCÊ", "RIVAL")
                cfg["derrota"] = "Seu rival venceu"
                cfg["linha_fim"] = "Você {a}  x  {b} Rival"
            pygame.display.set_caption(cfg["titulo"] + " (online)")
        self.cfg = cfg
        p = self.partida
        todas = list(p.baralho) + [c for j in p.jogadores for c in j.mao]
        self.sprites = {c: Sprite(c, *cfg["baralho"]) for c in todas}   # todas nascem no baralho
        self.recolhidas = {}          # carta -> equipe que levou (alvo do voo da vaza)
        self.ordem_compra = ordem     # quem compra primeiro (define o escalonamento)
        self.fila_rede = []
        self.particulas = []
        self.exib = {0: 0.0, 1: 0.0}  # pontos exibidos (contagem animada)
        self.pop = {0: 0.0, 1: 0.0}   # "soco" de escala no placar
        self.tremor = 0.0
        self.hover_carta = None
        self.hover_prev = None
        self.carta_vencedora = None
        self.aviso_txt, self.aviso_ate = "", 0
        self.textos = []
        self.rg_res = None
        self.rg_meta_ok = False
        self.exib_score = 0.0
        self.pulso_cur = [0.0] * MAX_CURINGAS
        if self.run:
            self.rg_conf = self.run.confronto
            self.rg_meta = self.run.meta()
        self.mensagem = "Distribuindo..."
        self.estado = "espera"
        self.evento_em = pygame.time.get_ticks() + 600 + 100 * p.n * MAO_TAMANHO

    def reiniciar(self):
        if not self.online:
            self.nova_partida()
        elif self.papel == "host":
            self.iniciar_online_host()
        else:
            self.avisar("Só o host pode reiniciar a partida")

    def avisar(self, msg, ms=2000):
        self.aviso_txt = msg
        self.aviso_ate = pygame.time.get_ticks() + ms

    def iniciar_vez(self):
        p = self.mao
        if p.terminou():
            if self.run:
                self.rg_fim_mao()
            else:
                self.estado = "fim"
                self.mensagem = ""
            return
        j = p.jogadores[p.vez]
        if p.vez == 0:
            self.estado = "humano"
            self.mensagem = "Sua vez: clique em uma carta"
            if not self.tip("basico") and self.run:
                self.tip("rg_pontos")
        elif j.tipo == "cpu":
            self.estado = "cpu"
            self.evento_em = pygame.time.get_ticks() + ATRASO_CPU
            self.mensagem = f"{j.nome} está pensando..."
        else:
            self.estado = "remoto"
            self.mensagem = f"Aguardando {j.nome}..."

    def apos_jogada(self):
        p = self.mao
        if p.vaza_completa:
            venc = p.vencedor_atual()
            pts = sum(p.pontos_de(c) for _, c in p.mesa)
            self.carta_vencedora = next(c for i, c in p.mesa if i == venc)
            self.mensagem = f"{p.jogadores[venc].nome} ganhou a mão (+{pts})"
            self.estado = "vaza"
            self.evento_em = pygame.time.get_ticks() + ATRASO_VAZA
        else:
            self.iniciar_vez()

    def resolver(self):
        """Marca as cartas da mesa como 'recolhidas' (voam p/ o placar) e roda a lógica."""
        p = self.mao
        venc = p.vencedor_atual()
        equipe = p.jogadores[venc].equipe
        pts = sum(p.pontos_de(c) for _, c in p.mesa)
        naipe = self.carta_vencedora.naipe
        for _, c in p.mesa:
            self.recolhidas[c] = equipe
        res = self.run.processar_vaza(p, venc) if self.run else None   # pontua ANTES das compras
        havia_baralho = bool(p.baralho)
        p.resolver_vaza()                                   # lógica intacta
        self.ordem_compra = [(venc + i) % p.n for i in range(p.n)]
        self.carta_vencedora = None
        self.explodir(naipe, min(110, 40 + pts * 4))
        self.tremor = max(self.tremor, min(12.0, 3 + pts * 0.5))
        self.pop[equipe] = 0.5
        if res is not None:
            self.rg_efeitos_vaza(res)
        else:
            px, py = PLACAR_POS[equipe]
            self.add_texto(f"+{pts}", px - 30, py + 4, DOURADO, vida=1.2)   # no lugar da mensagem de texto
            self.tip("vaza1")
        self.mensagem = ""
        self.estado = "espera"
        self.evento_em = pygame.time.get_ticks() + (350 + 110 * p.n if havia_baralho else 350)

    # ============================================================
    # MODO APOSTA: fluxo (mapa -> confronto -> loja -> ...)
    # ============================================================
    def iniciar_run(self):
        self.encerrar_rede()
        self.run = Run()
        self.save["runs"] += 1
        salvar_save(self.save)
        self.confirma_ate = 0
        self.ir_mapa()

    def ir_mapa(self):
        self.cena = "rg_mapa"
        self.aposta_sel = self.run.aposta
        self.cortina, self.cortina_alvo = 255.0, 0.0
        pygame.display.set_caption("Bisca - Modo Aposta")
        self.tip("rg_aposta")

    def rg_jogar(self):
        r = self.run
        r.iniciar_confronto(self.aposta_sel)
        self.nova_partida("1x1")
        self.cena = "jogo"
        self.cortina, self.cortina_alvo = 255.0, 0.0

    def ir_loja(self):
        self.run.gerar_loja()
        self.cena = "rg_loja"
        self.loja_sel = 0
        self.loja_msg = ("", BRANCO, 0)
        self.cortina, self.cortina_alvo = 255.0, 0.0
        pygame.display.set_caption("Bisca - Loja")
        self.tip("rg_loja")

    def rg_fim_mao(self):
        """A mão acabou: confere a meta, paga recompensa (ou tira vidas) e mostra o resultado."""
        res = self.run.fechar_confronto()
        self.rg_res = res
        self.estado = "rg_res"
        self.mensagem = ""
        if res["venceu"]:
            self.explodir(random.choice(NAIPES), 90)
            self.tremor = max(self.tremor, 8.0)

    def rg_continuar(self):
        r = self.run
        res = self.rg_res
        self.rg_res = None
        if r.fim:
            melhor = max(self.save["melhor_nivel"], min(r.nivel, NIVEL_FINAL))
            self.save["melhor_nivel"] = melhor
            if r.fim == "vitoria":
                self.save["vitorias"] += 1
            salvar_save(self.save)
            self.cena = "rg_fim"
            self.cortina, self.cortina_alvo = 255.0, 0.0
        elif res and res["venceu"]:
            self.ir_loja()
        else:
            self.ir_mapa()          # perdeu uma vida: tenta o mesmo confronto de novo

    def rg_efeitos_vaza(self, res):
        """Textos flutuantes: fichas, multiplicador, ganho e o que cada Curinga fez."""
        r = self.run
        if res["venci"]:
            self.add_texto(str(res["chips"]), CX - 70, CY - 60, AZUL_FICHA, vida=1.3)
            if abs(res["mult"] - 1) > 0.001:
                self.add_texto(f"x{res['mult']:g}", CX + 20, CY - 60, COR_MULT, atraso=0.3, vida=1.2)
            px, py = PLACAR_POS[0]
            self.add_texto(f"+{res['ganho']}", px - 40, py + 34, DOURADO, atraso=0.6, vida=1.3, fonte="f_num")
        for i, txt, cor in res["log"]:
            if i < MAX_CURINGAS:
                rc = self.rect_mini(i)
                self.add_texto(txt, rc.centerx, rc.top - 12, cor, atraso=0.15, vida=1.3, fonte="f_peq")
                self.pulso_cur[i] = 1.0
        if res["dinheiro"]:
            self.add_texto(f"+${res['dinheiro']}", LARGURA - 70, 200, COR_DINHEIRO, atraso=0.3, vida=1.2)
        if not self.rg_meta_ok and r.score >= r.meta():
            self.rg_meta_ok = True
            self.add_texto("META BATIDA!", CX, CY - 150, DOURADO, atraso=0.7, vida=1.9, vy=-8, fonte="f_gde")
            self.explodir(random.choice(NAIPES), 80, PLACAR_POS[0][0], PLACAR_POS[0][1] + 20)

    def confirmar_abandono(self):
        agora = pygame.time.get_ticks()
        if agora < self.confirma_ate:
            self.voltar_ao_menu()
        else:
            self.confirma_ate = agora + 2000
            self.avisar("ESC de novo para abandonar a run")

    def explodir(self, naipe, n, x=CX, y=CY):
        if len(self.particulas) > MAX_PARTICULAS:
            return
        cores = CORES_NAIPE[naipe]
        for _ in range(n):
            ang = random.uniform(0, math.tau)
            vel = random.uniform(120, 620)
            self.particulas.append(Particula(
                x + random.uniform(-30, 30), y + random.uniform(-20, 20),
                math.cos(ang) * vel, math.sin(ang) * vel - 60,
                random.choice(cores), random.uniform(0.5, 1.2), random.uniform(5, 12)))

    def atualizar(self, dt):
        self.t += dt
        self.cortina += (self.cortina_alvo - self.cortina) * (1 - 0.85 ** (dt * 60))
        for pt in self.particulas:
            pt.atualizar(dt)
        self.particulas = [pt for pt in self.particulas if pt.vida > 0]
        self.tremor *= 0.9 ** (dt * 60)
        self.atualizar_textos(dt)
        if self.papel:
            self.processar_rede()
        if self.cena == "menu":
            self.atualizar_menu(dt)
        elif self.cena == "mp":
            self.atualizar_mp(dt)
        elif self.cena in ("rg_mapa", "rg_loja", "rg_fim"):
            self.atualizar_rg(dt)
        else:
            self.atualizar_jogo(dt)

    def atualizar_rg(self, dt):
        for f in self.flutuantes:
            f.atualizar(dt)

    def atualizar_jogo(self, dt):
        agora = pygame.time.get_ticks()
        p = self.mao
        if self.tip_atual is None:          # uma dica na tela pausa o jogo
            if self.estado == "cpu" and agora >= self.evento_em:
                idx = p.vez
                carta = cpu_escolher(p, idx, self.perfil)
                p.jogar(idx, carta)
                self.enviar_jogada(idx, carta)
                self.apos_jogada()
            elif self.estado == "remoto":
                self.consumir_jogada_remota()
            elif self.estado == "vaza" and agora >= self.evento_em:
                self.resolver()
            elif self.estado == "espera" and agora >= self.evento_em:
                self.iniciar_vez()

        self.sincronizar()
        for s in self.sprites.values():
            s.atualizar(dt)

        # placar: contagem animada + pop
        for e in (0, 1):
            real = p.pontos[e]
            self.exib[e] += (real - self.exib[e]) * (1 - 0.9 ** (dt * 60))
            if abs(real - self.exib[e]) < 0.05:
                self.exib[e] = real
            self.pop[e] *= 0.9 ** (dt * 60)
        if self.run:
            self.exib_score += (self.run.score - self.exib_score) * (1 - 0.88 ** (dt * 60))
            if abs(self.run.score - self.exib_score) < 0.5:
                self.exib_score = float(self.run.score)
            for i in range(MAX_CURINGAS):
                self.pulso_cur[i] *= 0.9 ** (dt * 60)
        if self.estado == "fim" and p.resultado()[0] > p.resultado()[1] and random.random() < 0.04:
            self.explodir(random.choice(NAIPES), 30, random.randint(150, LARGURA - 150),
                          random.randint(120, ALTURA - 250))

    # ---------- layout ----------
    @staticmethod
    def slot_mao(i, n):
        """Posição-base (centro) e inclinação em leque da carta i na mão do jogador."""
        mid = (n - 1) / 2
        d = i - mid
        return CX + d * 122, ALTURA - CARTA_A // 2 - 30 + d * d * 5, -d * 3.5

    def indice_sob_mouse(self, pos):
        n = len(self.mao.jogadores[0].mao)
        for i in range(n):
            bx, by, _ = self.slot_mao(i, n)
            # a área sobe 36px para a carta levantada não "perder" o hover (evita flicker)
            r = pygame.Rect(bx - CARTA_L // 2, by - CARTA_A // 2 - 36, CARTA_L, CARTA_A + 36)
            if r.collidepoint(pos):
                return i
        return None

    def clique(self, pos):
        if self.estado != "humano":
            return
        p = self.mao
        i = self.indice_sob_mouse(pos)
        if i is not None:
            carta = p.jogadores[0].mao[i]
            p.jogar(0, carta)
            self.enviar_jogada(0, carta)
            self.apos_jogada()

    # ---------- sincronização lógica -> alvos dos sprites ----------
    def sincronizar(self):
        p, t, cfg = self.mao, self.t, self.cfg
        mouse = pygame.mouse.get_pos()
        revela = bool(self.run and self.run.revela())                 # Curinga 'Olho de Vidro'
        guia_turno = self.estado == "humano" and not self.dicas and not self.tip_atual

        # 1) onde cada carta está segundo a lógica: carta -> (zona, jogador, posição, total)
        info = {}
        for i, (idx, c) in enumerate(p.mesa):
            info[c] = ("mesa", idx, i, p.n)
        for idx, j in enumerate(p.jogadores):
            for i, c in enumerate(j.mao):
                info[c] = ("mao" if idx == 0 else "cpu", idx, i, len(j.mao))
        nb = len(p.baralho)
        for i, c in enumerate(p.baralho):
            info[c] = ("baralho", 0, i, nb)

        # 2) compras novas (baralho -> mão): escalonadas para sair uma de cada vez
        compras = []
        for c, inf in info.items():
            if self.sprites[c].zona == "baralho" and inf[0] in ("mao", "cpu"):
                compras.append((inf[2], self.ordem_compra.index(inf[1]), c))
        compras.sort(key=lambda x: (x[0], x[1]))
        for k, (_, _, c) in enumerate(compras):
            self.sprites[c].atraso = 0.08 + k * 0.1

        # 3) hover (só quando é a vez do jogador)
        hover_i = self.indice_sob_mouse(mouse) if self.estado == "humano" else None
        mao_h = p.jogadores[0].mao
        self.hover_carta = mao_h[hover_i] if hover_i is not None else None
        if self.hover_carta is not None and self.hover_carta != self.hover_prev:
            sp = self.sprites[self.hover_carta]       # "chacoalhada" ao entrar com o mouse
            sp.rot += random.choice((-7, 7))
            sp.esc = 1.22
        self.hover_prev = self.hover_carta

        # 4) define o ALVO de cada sprite conforme a zona
        for c, s in self.sprites.items():
            inf = info.get(c)
            zona = inf[0] if inf else "recolhida"
            if zona != s.zona and zona == "mesa":     # acabou de ser jogada
                s.chegou = False
                s.rot_mesa = random.uniform(-7, 7)
                s.esc += 0.3                           # "pop" ao sair da mão
            s.zona = zona
            s.visivel = True
            s.aalpha = 255.0
            s.aelev = 0.0
            destaque = (c == self.hover_carta) or (c == self.carta_vencedora)
            s.brilho = destaque or (guia_turno and zona == "mao")
            s.brilho_a = 255 if destaque else int(110 + 100 * math.sin(t * 4))

            if zona == "mao":                           # WOBBLE & TILT
                _, _, i, n = inf
                bx, by, rot = self.slot_mao(i, n)
                s.ordem, s.aface = i, 1.0
                if c == self.hover_carta:
                    dx = limitar((mouse[0] - bx) / (CARTA_L / 2), -1, 1)
                    s.ax, s.ay = bx, by - 34                 # levanta
                    s.arot = rot * 0.2 - dx * 8              # inclina para o lado do mouse
                    s.aesc, s.vel, s.aelev = 1.14, 0.3, 24   # cresce
                else:                                         # flutua, defasada pelo índice
                    s.ax = bx + math.cos(t * 1.1 + i * 2.3) * 2.5
                    s.ay = by + math.sin(t * 1.7 + i * 1.9) * 4
                    s.arot = rot + math.sin(t * 1.3 + i * 2.1) * 2
                    s.aesc, s.vel = 1.0, 0.2
            elif zona == "cpu":
                _, idx, i, n = inf
                lado = cfg["lados"][idx]
                d = i - (n - 1) / 2
                w1 = math.cos(t * 1.1 + i * 2.3)
                w2 = math.sin(t * 1.7 + i * 1.9)
                w3 = math.sin(t * 1.3 + i * 2.1)
                s.ordem, s.aface, s.vel = i, (1.0 if revela else 0.0), 0.2
                if lado == "cima":
                    s.ax = CX + d * 74 + w1 * 2
                    s.ay = 76 - d * d * 5 + w2 * 3
                    s.arot = d * 3.5 + w3 * 1.5
                    s.aesc = 1.0
                else:                                     # mãos laterais: leque na vertical
                    esq = lado == "esq"
                    sinal = 1 if esq else -1
                    s.ax = (52 if esq else LARGURA - 52) + sinal * d * d * 4 + w1 * 2
                    s.ay = CY + d * 64 + w2 * 3
                    s.arot = (90 if esq else -90) + sinal * d * 3.5 + w3 * 1.5
                    s.aesc = 0.72
            elif zona == "mesa":
                _, idx, pos, _ = inf
                bx, by = cfg["mesa"][idx]
                s.ordem, s.aface, s.vel, s.aelev = pos, 1.0, 0.3, 6
                s.ax = bx
                s.ay = by + math.sin(t * 2 + idx) * 2
                s.arot = s.rot_mesa + math.sin(t * 1.5 + idx) * 1.2
                pulso = 1.08 + math.sin(t * 9) * 0.03 if c == self.carta_vencedora else 1.0
                s.aesc = pulso * cfg["esc_mesa"]
                if not s.chegou and s.atraso <= 0 and s.dist() < 14:   # impacto ao pousar
                    s.chegou = True
                    s.esc = 1.2
                    self.tremor = max(self.tremor, 3.0)
            elif zona == "baralho":
                _, _, i, n = inf
                s.ordem = i
                s.vel = 0.28
                if i == 0:                                # carta do trunfo, deitada sob o monte
                    s.ax, s.ay, s.arot, s.aface = cfg["trunfo"][0], cfg["trunfo"][1], 90.0, 1.0
                    s.visivel = True
                else:
                    d = n - 1 - i
                    k = min(d, 5)
                    s.ax, s.ay = cfg["baralho"][0] - k * 1.5, cfg["baralho"][1] - k * 1.5
                    s.arot, s.aface = 0.0, 0.0
                    s.visivel = d < 5                      # só desenha o topo do monte
                s.aesc = 1.0
            else:                                           # recolhida: voa p/ o placar e some
                eq = self.recolhidas.get(c, 0)
                s.ax, s.ay = PLACAR_POS[eq]
                s.arot = 320.0 if s.rot_mesa > 0 else -320.0
                s.aesc, s.aalpha, s.aface, s.vel = 0.22, 0.0, 1.0, 0.26
                s.ordem = 0
                s.visivel = s.alpha > 6

    # ---------- desenho ----------
    @staticmethod
    def _z(s, hover_carta):
        base = {"baralho": 10, "cpu": 100, "mao": 200, "mesa": 400, "recolhida": 500}[s.zona] + s.ordem
        if s.zona != "baralho" and s.atraso <= 0 and s.dist() > 30:
            base += 600                                    # cartas em voo ficam por cima
        if s.carta == hover_carta:
            base += 300
        return base

    def desenhar_sprite(self, s):
        v = self.vis
        base = v.face(s.carta) if s.face > 0.5 else v.verso
        sombra = v.sombra
        sx = max(0.04, abs(math.cos(math.pi * s.face)))   # flip: a carta "vira" em torno do eixo Y
        if sx < 0.995:
            w = max(2, int(CARTA_L * sx))
            base = pygame.transform.smoothscale(base, (w, CARTA_A))
            sombra = pygame.transform.smoothscale(sombra, (w, CARTA_A))
        esc = max(0.05, s.esc)
        if abs(s.rot) > 0.2 or abs(esc - 1) > 0.01:
            base = pygame.transform.rotozoom(base, s.rot, esc)
            sombra = pygame.transform.rotozoom(sombra, s.rot, esc)
        a = int(limitar(s.alpha, 0, 255))
        elev = s.elev + min(18.0, s.dist() * 0.08)         # sombra se afasta quando a carta "sobe"
        sombra.set_alpha(a)
        self.tela.blit(sombra, sombra.get_rect(center=(s.x + 3 + elev * 0.25, s.y + 7 + elev * 0.7)))
        if s.brilho:
            g = pygame.transform.rotozoom(v.contorno, s.rot, esc)
            g.set_alpha(int(s.brilho_a))
            self.tela.blit(g, g.get_rect(center=(s.x, s.y)))
        base.set_alpha(a)
        self.tela.blit(base, base.get_rect(center=(s.x, s.y)))

    def desenhar_cartas(self):
        visiveis = [s for s in self.sprites.values() if s.visivel]
        for s in sorted(visiveis, key=lambda s: self._z(s, self.hover_carta)):
            self.desenhar_sprite(s)

    def desenhar_particulas(self):
        v = self.vis
        for pt in self.particulas:
            raio = max(3, int(pt.tam * (0.25 + 0.75 * pt.frac)))
            self.tela.blit(v.brilho(pt.cor, raio), (int(pt.x) - raio, int(pt.y) - raio),
                           special_flags=pygame.BLEND_RGB_ADD)
            nucleo = max(2, raio // 3)
            self.tela.blit(v.brilho((255, 255, 255), nucleo), (int(pt.x) - nucleo, int(pt.y) - nucleo),
                           special_flags=pygame.BLEND_RGB_ADD)

    def desenhar_rotulos(self):
        """Nome de cada adversário/parceiro (2x2); o da vez pisca em dourado."""
        if self.modo != "2x2":
            return
        t, v, p = self.tela, self.vis, self.mao
        posicoes = {"cima": (CX, 168), "esq": (52, CY + 122), "dir": (LARGURA - 52, CY + 122)}
        for idx, lado in enumerate(self.cfg["lados"]):
            if lado == "baixo":
                continue
            j = p.jogadores[idx]
            ativo = self.estado in ("cpu", "remoto", "humano") and p.vez == idx
            cor = DOURADO if ativo else (AZUL_EQ if j.equipe == 0 else VERMELHO_EQ)
            x, y = posicoes[lado]
            texto(t, v.f_peq, j.nome, cor, (x, y + (math.sin(self.t * 6) * 3 if ativo else 0)))

    # ============================================================
    # DICAS (cada uma aparece UMA vez) E TEXTOS FLUTUANTES
    # ============================================================
    def tip(self, chave):
        """Mostra a dica `chave` se ainda não foi vista. Retorna True se começou a mostrar."""
        if self.online or self.tip_atual or chave in self.save["vistas"] or chave not in TIPS:
            return False
        self.tip_atual = {"chave": chave, "pag": 0}
        return True

    def avancar_tip(self):
        tp = self.tip_atual
        if not tp:
            return
        tp["pag"] += 1
        if tp["pag"] >= len(TIPS[tp["chave"]]):
            self.save["vistas"].append(tp["chave"])
            salvar_save(self.save)
            if tp["chave"] == "vaza1":
                self.dicas = False          # tutorial concluído: a tela fica só com sinais visuais
            self.tip_atual = None

    def refazer_tutorial(self):
        self.save["vistas"] = []
        salvar_save(self.save)
        self.dicas = True
        self.menu_aviso = "Tutorial reiniciado: ele aparece na próxima partida"
        self.menu_aviso_ate = pygame.time.get_ticks() + 3000

    def _seta(self, alvo, origem):
        ax, ay = alvo
        dx, dy = ax - origem[0], ay - origem[1]
        d = math.hypot(dx, dy) or 1.0
        ux, uy = dx / d, dy / d
        bob = math.sin(self.t * 6) * 5
        px, py = ax - ux * (6 + bob), ay - uy * (6 + bob)       # ponta
        bx, by = px - ux * 30, py - uy * 30                      # base
        nx, ny = -uy * 16, ux * 16
        pygame.draw.polygon(self.tela, (0, 0, 0), [(px + 2, py + 3), (bx + nx + 2, by + ny + 3), (bx - nx + 2, by - ny + 3)])
        pygame.draw.polygon(self.tela, DOURADO, [(px, py), (bx + nx, by + ny), (bx - nx, by - ny)])

    def desenhar_tip(self):
        tp = self.tip_atual
        if not tp:
            return
        pags = TIPS[tp["chave"]]
        pag = pags[tp["pag"]]
        t, v = self.tela, self.vis
        t.blit(v.veu_tip, (0, 0))
        linhas = pag["linhas"]
        ls = v.f_peq.get_linesize() + 8
        w = max(v.f_peq.size(l)[0] for l in linhas) + 60
        h = len(linhas) * ls + 70
        nome = pag["alvo"]
        if nome == "trunfo":
            cx, cy = 90 + w // 2 + 60, 260
        elif nome == "placar":
            cx, cy = LARGURA - 40 - w // 2, 330
        elif nome == "mao":
            cx, cy = CX, ALTURA - 360
        else:
            cx, cy = CX, CY - 40
        cx = int(limitar(cx, w // 2 + 16, LARGURA - w // 2 - 16))
        r = pygame.Rect(0, 0, w, h)
        r.center = (cx, cy)
        v.painel(t, r, DOURADO)
        y = r.y + 34
        for i, ln in enumerate(linhas):
            if ln:
                texto(t, v.f_peq, ln, DOURADO if i == 0 else BRANCO, (r.centerx, y))
            y += ls
        pulso = CINZA if int(self.t * 2) % 2 else BRANCO
        texto(t, v.f_peq, f"clique ou ENTER  ({tp['pag'] + 1}/{len(pags)})", pulso, (r.centerx, r.bottom - 22))
        if nome in ANCORAS:
            self._seta(ANCORAS[nome], r.center)

    def add_texto(self, txt, x, y, cor, atraso=0.0, vida=1.1, vy=-50.0, fonte="f_med", esc=1.0):
        self.textos.append({"txt": txt, "x": float(x), "y": float(y), "cor": cor, "atraso": atraso,
                            "vida": vida, "t": 0.0, "vy": vy, "fonte": fonte, "esc": esc})

    def atualizar_textos(self, dt):
        for tx in self.textos:
            if tx["atraso"] > 0:
                tx["atraso"] -= dt
                continue
            tx["t"] += dt
            tx["y"] += tx["vy"] * dt
            tx["vy"] *= 0.96 ** (dt * 60)
        self.textos = [tx for tx in self.textos if tx["t"] < tx["vida"]]

    def desenhar_textos(self):
        v = self.vis
        for tx in self.textos:
            if tx["atraso"] > 0:
                continue
            f = getattr(v, tx["fonte"])
            esc = tx["esc"] * (1 + 0.6 * max(0.0, 1 - tx["t"] / 0.18))     # "pop" ao aparecer
            a = int(255 * limitar((tx["vida"] - tx["t"]) / 0.3, 0, 1))      # some no final
            img = pygame.transform.rotozoom(_render(f, tx["txt"], tx["cor"]), 0, esc)
            sh = pygame.transform.rotozoom(_render(f, tx["txt"], (0, 0, 0)), 0, esc)
            img.set_alpha(a)
            sh.set_alpha(a)
            r = img.get_rect(center=(tx["x"], tx["y"]))
            self.tela.blit(sh, r.move(2, 3))
            self.tela.blit(img, r)

    # ============================================================
    # CURINGAS: desenho
    # ============================================================
    def _etiqueta(self, centro, txt, cor):
        t, v = self.tela, self.vis
        r = pygame.Rect(0, 0, 76, 28)
        r.center = centro
        pygame.draw.rect(t, (10, 8, 20), r, border_radius=8)
        pygame.draw.rect(t, cor, r, 2, border_radius=8)
        texto(t, v.f_peq, txt, cor, r.center, sombra=False)

    def desenhar_carta_curinga(self, cid, centro, esc=1.0, rot=0.0, preco=None, cor_preco=DOURADO,
                               destaque=False, apagada=False):
        img = self.vis.curinga(cid)
        if esc != 1.0 or abs(rot) > 0.05:
            img = pygame.transform.rotozoom(img, rot, esc)
        else:
            img = img.copy()
        if apagada:
            img.set_alpha(90)
        r = img.get_rect(center=centro)
        pygame.draw.rect(self.tela, (0, 0, 0), r.move(4, 8), border_radius=12)
        if destaque:
            pygame.draw.rect(self.tela, DOURADO, r.inflate(10, 10), 4, border_radius=16)
        self.tela.blit(img, r)
        if preco is not None:
            self._etiqueta((r.centerx, r.bottom + 16), preco, cor_preco)
        return r

    def desenhar_tooltip(self, cid, ancora):
        """Caixa com nome e descrição de um Curinga, acima do ponto `ancora` (centro-baixo)."""
        t, v = self.tela, self.vis
        d = CURINGAS[cid]
        linhas = quebrar(v.f_peq, d["desc"], 380)
        ls = v.f_peq.get_linesize() + 4
        r = pygame.Rect(0, 0, 420, 50 + len(linhas) * ls)
        r.midbottom = ancora
        r.clamp_ip(pygame.Rect(8, 8, LARGURA - 16, ALTURA - 16))
        v.painel(t, r, RARIDADES[d["rar"]][0])
        texto(t, v.f_peq, d["nome"], DOURADO, (r.x + 20, r.y + 24), "midleft")
        for i, ln in enumerate(linhas):
            texto(t, v.f_peq, ln, BRANCO, (r.x + 20, r.y + 50 + i * ls), "midleft")

    def rect_mini(self, i):
        r = pygame.Rect(0, 0, 62, 92)
        r.center = (20 + 31 + i * 70, ALTURA - 118)
        return r

    def desenhar_curingas_hud(self):
        """Fileira de Curingas no canto inferior esquerdo, durante o confronto."""
        r = self.run
        for i in range(MAX_CURINGAS):
            rc = self.rect_mini(i)
            if i >= len(r.curingas):
                pygame.draw.rect(self.tela, (70, 64, 96), rc, 2, border_radius=8)
                continue
            mudo = self.rg_conf.regra == "silencio" and i == 0
            pul = self.pulso_cur[i]
            self.desenhar_carta_curinga(r.curingas[i]["id"], rc.center, 0.40 * (1 + 0.3 * pul),
                                        math.sin(self.t * 2 + i) * 2 + pul * 6 * math.sin(self.t * 30),
                                        apagada=mudo)

    # ============================================================
    # MODO APOSTA: telas (mapa, loja, fim da run)
    # ============================================================
    def desenhar_rg_topo(self, titulo):
        t, v, r = self.tela, self.vis, self.run
        texto(t, v.f_gde, titulo, DOURADO, (CX, 56 + math.sin(self.t * 2) * 3))
        texto(t, v.f_med, f"${r.dinheiro}", COR_DINHEIRO, (LARGURA - 30, 34), "midright")
        for i in range(MAX_VIDAS):
            cor = COR_NAIPE["copas"] if i < r.vidas else (70, 64, 96)
            desenhar_naipe(t, "copas", LARGURA - 40 - i * 30, 78, 24, cor)

    def rects_mapa(self):
        ap = []
        for i in range(3):
            r = pygame.Rect(0, 0, 220, 84)
            r.center = (CX - 240 + 240 * i, 548)
            ap.append(r)
        jogar = pygame.Rect(0, 0, 260, 56)
        jogar.center = (CX, 652)
        return ap, jogar

    def desenhar_mapa(self):
        t, v, r = self.tela, self.vis, self.run
        t.blit(v.fundo(self.t, True), (0, 0))
        self.desenhar_flutuantes()
        self.desenhar_rg_topo(f"NÍVEL {min(r.nivel, NIVEL_FINAL)} / {NIVEL_FINAL}")
        for i in range(3):                                       # progresso do nível
            rc = pygame.Rect(0, 0, 220, 52)
            rc.center = (CX - 240 + 240 * i, 128)
            feito, atual = i < r.etapa, i == r.etapa
            v.painel(t, rc, VERDE if feito else (DOURADO if atual else (80, 74, 110)),
                     (40, 34, 66) if atual else (28, 24, 48))
            texto(t, v.f_peq, ("OK  " if feito else "") + ETAPA_CURTA[i], BRANCO if (atual or feito) else CINZA, rc.center)
        c = r.confronto
        pr = pygame.Rect(CX - 360, 170, 720, 262)
        v.painel(t, pr, DOURADO)
        av = pygame.transform.rotozoom(v.verso, math.sin(self.t * 1.5) * 4, 1.0)
        t.blit(av, av.get_rect(center=(pr.x + 100, pr.centery)))
        desenhar_naipe(t, c.oponente.naipe, pr.x + 100, pr.centery, 46, CORES_NAIPE[c.oponente.naipe][0])
        x0, larg = pr.x + 190, pr.w - 210
        y = pr.y + 30
        for ln in quebrar(v.f_med, c.oponente.nome, larg)[:2]:
            texto(t, v.f_med, ln, BRANCO, (x0, y), "midleft")
            y += 36
        perfil = PERFIS[c.oponente.perfil]
        y += 8
        texto(t, v.f_peq, f"Perfil: {perfil['nome']}", AZUL_FICHA, (x0, y), "midleft")
        y += 26
        for ln in quebrar(v.f_peq, perfil["desc"], larg)[:1]:
            texto(t, v.f_peq, ln, CINZA, (x0, y), "midleft")
            y += 24
        y += 14
        if c.regra:
            nome, desc = REGRAS[c.regra]
            texto(t, v.f_peq, f"REGRA: {nome}", DOURADO, (x0, y), "midleft")
            y += 26
            for ln in quebrar(v.f_peq, desc, larg)[:2]:
                texto(t, v.f_peq, ln, BRANCO, (x0, y), "midleft")
                y += 24
        else:
            texto(t, v.f_peq, "Sem regras especiais", CINZA, (x0, y), "midleft")
        sel = self.aposta_sel
        texto(t, v.f_med, f"META {r.meta(sel)}", BRANCO, (CX - 170, 466))
        texto(t, v.f_med, f"RECOMPENSA ${r.recompensa_base(sel)}", COR_DINHEIRO, (CX + 170, 466))
        ap, jogar = self.rects_mapa()
        for i, (nome, mm, mr, vd) in enumerate(APOSTAS):
            rc = ap[i]
            ativo = i == sel
            rr = rc.move(0, -8 if ativo else 0)
            v.painel(t, rr, DOURADO if ativo else (120, 110, 170), (40, 34, 66) if ativo else (28, 24, 48))
            texto(t, v.f_med, nome, DOURADO if ativo else BRANCO, (rr.centerx, rr.y + 26))
            texto(t, v.f_peq, f"meta x{mm:g}   prêmio x{mr}", CINZA, (rr.centerx, rr.y + 54))
            for k in range(vd):
                desenhar_naipe(t, "copas", rr.right - 22 - k * 20, rr.y + 20, 16, COR_NAIPE["copas"])
        v.painel(t, jogar, DOURADO, (60, 52, 20))
        texto(t, v.f_med, "JOGAR", DOURADO, jogar.center)
        texto(t, v.f_peq, "← → : aposta    ENTER: jogar    ESC (2x): abandonar", (190, 190, 215), (CX, ALTURA - 20))

    def evento_mapa(self, e):
        ap, jogar = self.rects_mapa()
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                self.confirmar_abandono()
            elif e.key in (pygame.K_LEFT, pygame.K_a):
                self.aposta_sel = max(0, self.aposta_sel - 1)
            elif e.key in (pygame.K_RIGHT, pygame.K_d):
                self.aposta_sel = min(len(APOSTAS) - 1, self.aposta_sel + 1)
            elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self.rg_jogar()
        elif e.type == pygame.MOUSEMOTION:
            for i, rc in enumerate(ap):
                if rc.collidepoint(e.pos):
                    self.aposta_sel = i
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            for i, rc in enumerate(ap):
                if rc.collidepoint(e.pos):
                    self.aposta_sel = i
            if jogar.collidepoint(e.pos):
                self.rg_jogar()

    # ---------- loja ----------
    def rects_loja(self):
        rr = {"of": [], "meu": []}
        for i in range(4):
            r = pygame.Rect(0, 0, 156, 230)
            r.center = (CX - 264 + 176 * i, 235)
            rr["of"].append(r)
        for i in range(MAX_CURINGAS):
            r = pygame.Rect(0, 0, 115, 170)
            r.center = (CX - 272 + 136 * i, 605)
            rr["meu"].append(r)
        for nome, y in (("reroll", 190), ("prox", 280)):
            r = pygame.Rect(0, 0, 170, 56)
            r.center = (990, y)
            rr[nome] = r
        return rr

    def itens_loja(self):
        r = self.run
        out = [("of", i) for i, cid in enumerate(r.oferta) if cid is not None]
        if not r.vida_comprada:
            out.append(("vida", 0))
        out += [("meu", i) for i in range(len(r.curingas))]
        out += [("reroll", 0), ("prox", 0)]
        return out

    def rect_item(self, item, rr=None):
        rr = rr or self.rects_loja()
        k, i = item
        if k == "of":
            return rr["of"][i]
        if k == "vida":
            return rr["of"][3]
        if k == "meu":
            return rr["meu"][i]
        return rr[k]

    def loja_msg_set(self, ok, msg):
        if msg:
            self.loja_msg = (msg, COR_DINHEIRO if ok else VERMELHO_EQ, pygame.time.get_ticks() + 2200)

    def loja_ativar(self, item):
        r = self.run
        k, i = item
        centro = self.rect_item(item).center
        if k == "of":
            ok, msg = r.comprar(i)
        elif k == "vida":
            ok, msg = r.comprar_vida()
        elif k == "reroll":
            ok, msg = r.reroll()
        elif k == "prox":
            self.ir_mapa()
            return
        else:
            return
        self.loja_msg_set(ok, msg)
        if ok and k != "reroll":
            self.explodir(random.choice(NAIPES), 40, *centro)

    def loja_vender(self, i):
        ok, msg = self.run.vender(i)
        self.loja_msg_set(ok, msg)
        self.loja_sel = 0

    def evento_loja(self, e):
        itens = self.itens_loja()
        rr = self.rects_loja()
        self.loja_sel = int(limitar(self.loja_sel, 0, len(itens) - 1))
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                self.confirmar_abandono()
            elif e.key in (pygame.K_LEFT, pygame.K_a, pygame.K_UP, pygame.K_w):
                self.loja_sel = (self.loja_sel - 1) % len(itens)
            elif e.key in (pygame.K_RIGHT, pygame.K_d, pygame.K_DOWN, pygame.K_s) and e.key != pygame.K_s:
                self.loja_sel = (self.loja_sel + 1) % len(itens)
            elif e.key == pygame.K_s:
                if itens[self.loja_sel][0] == "meu":
                    self.loja_vender(itens[self.loja_sel][1])
            elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self.loja_ativar(itens[self.loja_sel])
        elif e.type == pygame.MOUSEMOTION:
            for idx, it in enumerate(itens):
                if self.rect_item(it, rr).collidepoint(e.pos):
                    self.loja_sel = idx
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button in (1, 3):
            for idx, it in enumerate(itens):
                if self.rect_item(it, rr).collidepoint(e.pos):
                    self.loja_sel = idx
                    if e.button == 1:
                        self.loja_ativar(it)
                    elif it[0] == "meu":
                        self.loja_vender(it[1])
                    break

    def desenhar_loja(self):
        t, v, r = self.tela, self.vis, self.run
        t.blit(v.fundo(self.t, True), (0, 0))
        self.desenhar_flutuantes()
        self.desenhar_rg_topo("LOJA")
        rr = self.rects_loja()
        itens = self.itens_loja()
        self.loja_sel = int(limitar(self.loja_sel, 0, len(itens) - 1))
        sel = itens[self.loja_sel]
        for i, cid in enumerate(r.oferta):
            rc = rr["of"][i]
            if cid is None:
                pygame.draw.rect(t, (60, 54, 90), rc, 3, border_radius=12)
                texto(t, v.f_peq, "VENDIDO", CINZA, rc.center)
                continue
            ativo = sel == ("of", i)
            custo = CURINGAS[cid]["custo"]
            self.desenhar_carta_curinga(cid, (rc.centerx, rc.centery - (10 if ativo else 0)), 1.0,
                                        math.sin(self.t * 3 + i) * 1.5 if ativo else 0.0, preco=f"${custo}",
                                        cor_preco=COR_DINHEIRO if r.dinheiro >= custo else VERMELHO_EQ, destaque=ativo)
        rc = rr["of"][3]                                           # 4º item: vida extra
        if r.vida_comprada:
            pygame.draw.rect(t, (60, 54, 90), rc, 3, border_radius=12)
            texto(t, v.f_peq, "ESGOTADO", CINZA, rc.center)
        else:
            ativo = sel == ("vida", 0)
            rv = rc.move(0, -10 if ativo else 0)
            v.painel(t, rv, DOURADO if ativo else (120, 110, 170), (40, 34, 66))
            desenhar_naipe(t, "copas", rv.centerx, rv.centery - 20, 70, COR_NAIPE["copas"])
            texto(t, v.f_med, "+1 VIDA", BRANCO, (rv.centerx, rv.centery + 56))
            custo = r.custo_vida()
            self._etiqueta((rv.centerx, rv.bottom + 16), f"${custo}", COR_DINHEIRO if r.dinheiro >= custo else VERMELHO_EQ)
        for nome, rot in (("reroll", f"REROLL ${r.custo_reroll()}"), ("prox", "PRÓXIMO")):
            ativo = sel == (nome, 0)
            rb = rr[nome]
            v.painel(t, rb, DOURADO if ativo else (120, 110, 170), (60, 52, 20) if ativo else (28, 24, 48))
            texto(t, v.f_peq, rot, DOURADO if ativo else BRANCO, rb.center)
        # descrição do item selecionado
        dr = pygame.Rect(CX - 380, 390, 760, 86)
        v.painel(t, dr, (120, 110, 170))
        k, i = sel
        if k in ("of", "meu"):
            cid = r.oferta[i] if k == "of" else r.curingas[i]["id"]
            d = CURINGAS[cid]
            texto(t, v.f_peq, f"{d['nome']}  ({d['rar']})", RARIDADES[d["rar"]][0], (dr.x + 20, dr.y + 20), "midleft")
            for n, ln in enumerate(quebrar(v.f_peq, d["desc"], 720)[:2]):
                texto(t, v.f_peq, ln, BRANCO, (dr.x + 20, dr.y + 46 + n * 24), "midleft")
            if k == "meu":
                texto(t, v.f_peq, f"S / botão direito: vender por ${r.valor_venda(i)}", COR_MULT,
                      (dr.right - 16, dr.y + 20), "midright")
        else:
            txt = {"vida": f"Terço: +1 vida (máx. {MAX_VIDAS}). Uma vez por loja.",
                   "reroll": "Renova as cartas da loja. O preço sobe a cada vez.",
                   "prox": "Seguir para a próxima aposta."}[k]
            texto(t, v.f_peq, txt, BRANCO, (dr.x + 20, dr.centery), "midleft")
        texto(t, v.f_peq, f"SEUS CURINGAS  {len(r.curingas)}/{MAX_CURINGAS}", BRANCO, (CX, 498))
        for i in range(MAX_CURINGAS):
            rc = rr["meu"][i]
            if i >= len(r.curingas):
                pygame.draw.rect(t, (70, 64, 96), rc, 3, border_radius=10)
                continue
            ativo = sel == ("meu", i)
            self.desenhar_carta_curinga(r.curingas[i]["id"], (rc.centerx, rc.centery - (8 if ativo else 0)), 0.74,
                                        math.sin(self.t * 3 + i) * 1.5 if ativo else 0.0,
                                        preco=f"${r.valor_venda(i)}", cor_preco=COR_MULT, destaque=ativo)
        self.desenhar_particulas()
        msg, cor, ate = self.loja_msg
        if msg and pygame.time.get_ticks() < ate:
            texto(t, v.f_peq, msg, cor, (CX, ALTURA - 20))
        else:
            texto(t, v.f_peq, "←/→: escolher   ENTER: comprar   S: vender   ESC (2x): abandonar", (190, 190, 215),
                  (CX, ALTURA - 20))

    def desenhar_rg_fim(self):
        t, v, r = self.tela, self.vis, self.run
        t.blit(v.fundo(self.t, True), (0, 0))
        self.desenhar_flutuantes()
        vit = r.fim == "vitoria"
        texto(t, v.f_gde, "VITÓRIA!" if vit else "FIM DA RUN", DOURADO if vit else (255, 120, 110),
              (CX, 120 + math.sin(self.t * 2) * 5), escala=1 + math.sin(self.t * 3) * 0.04)
        linhas = [f"Nível alcançado: {min(r.nivel, NIVEL_FINAL)} / {NIVEL_FINAL}",
                  f"Confrontos vencidos: {r.vitorias}",
                  f"Melhor run: nível {self.save['melhor_nivel']}"]
        for i, ln in enumerate(linhas):
            texto(t, v.f_med, ln, BRANCO, (CX, 220 + i * 44))
        texto(t, v.f_peq, "SEUS CURINGAS", CINZA, (CX, 390))
        for i, st in enumerate(r.curingas):
            self.desenhar_carta_curinga(st["id"], (CX - 272 + 136 * i, 520), 0.74)
        self.desenhar_particulas()
        texto(t, v.f_peq, "ENTER: nova run   |   ESC: menu", (205, 205, 225), (CX, ALTURA - 22))

    def evento_rg_fim(self, e):
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                self.voltar_ao_menu()
            elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self.iniciar_run()

    # ============================================================
    # JOGO: desenho
    # ============================================================
    def desenhar_hud_rogue(self):
        """No Modo Aposta o painel de placar mostra META x PONTOS (fichas x mult), nível, $ e vidas."""
        t, v, r = self.tela, self.vis, self.run
        meta = self.rg_meta
        ok = r.score >= meta
        painel = pygame.Rect(LARGURA - 250, 16, 234, 106)
        v.painel(t, painel, DOURADO if ok else (120, 110, 170))
        texto(t, v.f_med, "META", AZUL_FICHA, (painel.x + 16, PLACAR_POS[0][1]), "midleft")
        texto(t, v.f_num, str(meta), BRANCO, (painel.right - 18, PLACAR_POS[0][1]), "midright")
        texto(t, v.f_med, "PONTOS", DOURADO if ok else COR_MULT, (painel.x + 16, PLACAR_POS[1][1]), "midleft")
        texto(t, v.f_num, str(int(round(self.exib_score))), DOURADO if ok else BRANCO,
              (painel.right - 18, PLACAR_POS[1][1]), "midright")
        barra = pygame.Rect(painel.x + 14, painel.bottom - 13, painel.w - 28, 6)
        pygame.draw.rect(t, (10, 8, 20), barra, border_radius=3)
        pygame.draw.rect(t, DOURADO if ok else COR_MULT, (barra.x, barra.y, int(barra.w * min(1.0, self.exib_score / max(1, meta))), barra.h),
                         border_radius=3)
        info = pygame.Rect(LARGURA - 250, 136, 234, 90)
        v.painel(t, info, (120, 110, 170))
        c = self.rg_conf
        texto(t, v.f_peq, f"NÍVEL {c.nivel} - {ETAPA_CURTA[c.etapa]}", BRANCO, (info.centerx, info.y + 24))
        texto(t, v.f_med, f"${r.dinheiro}", COR_DINHEIRO, (info.x + 16, info.y + 60), "midleft")
        for i in range(min(r.vidas, MAX_VIDAS)):
            desenhar_naipe(t, "copas", info.right - 24 - i * 22, info.y + 60, 18, COR_NAIPE["copas"])
        # rival e regra do confronto (canto inferior direito)
        op = pygame.Rect(LARGURA - 340, ALTURA - 116, 324, 100)
        v.painel(t, op, (120, 110, 170))
        y = op.y + 22
        for ln in quebrar(v.f_peq, c.oponente.nome, 290)[:2]:
            texto(t, v.f_peq, ln, BRANCO, (op.x + 18, y), "midleft")
            y += 24
        if c.regra:
            texto(t, v.f_peq, REGRAS[c.regra][0], DOURADO, (op.x + 18, y + 4), "midleft")

    def desenhar_hud(self):
        t, v, p, cfg = self.tela, self.vis, self.mao, self.cfg
        # trunfo
        r = pygame.Rect(20, 16, 124, 92)
        v.painel(t, r, DOURADO)
        texto(t, v.f_peq, "TRUNFO", BRANCO, (r.centerx, r.y + 18))
        chip = pygame.Rect(0, 0, 64, 44)
        chip.center = (r.centerx, r.y + 58)
        pygame.draw.rect(t, (250, 248, 240), chip, border_radius=10)
        desenhar_naipe(t, p.trunfo, chip.centerx, chip.centery, 26 + math.sin(self.t * 3) * 2,
                       COR_NAIPE[p.trunfo])
        if not p.trunfos:                                   # regra "Sem Trunfo": risca o naipe
            pygame.draw.line(t, (255, 60, 60), chip.bottomleft, chip.topright, 5)
        elif len(p.trunfos) > 1:                            # regra "Dois Trunfos": mostra o segundo naipe
            extra = next(n for n in p.trunfos if n != p.trunfo)
            desenhar_naipe(t, extra, chip.right - 4, chip.bottom - 2, 16, COR_NAIPE[extra])
        if self.run:
            self.desenhar_hud_rogue()
        else:
            painel = pygame.Rect(LARGURA - 250, 16, 234, 106)
            v.painel(t, painel, (120, 110, 170))
            for eq, nome, cor in ((0, cfg["placar"][0], AZUL_EQ), (1, cfg["placar"][1], VERMELHO_EQ)):
                y = PLACAR_POS[eq][1]
                texto(t, v.f_med, nome, cor, (painel.x + 16, y), "midleft")
                texto(t, v.f_num, str(int(round(self.exib[eq]))), BRANCO, (painel.right - 18, y),
                      "midright", escala=1 + self.pop[eq])
        bx, _ = cfg["baralho"]
        if self.dicas:
            texto(t, v.f_peq, f"Baralho: {len(p.baralho)}", BRANCO, (bx - 30, CY + CARTA_A // 2 + 34))
            dica = "ESC: sair da sala" if self.online else ("ESC (2x): abandonar a run" if self.run else "R: reiniciar   ESC: menu")
            texto(t, v.f_peq, dica + "   F1: dicas", (190, 190, 215), (16, ALTURA - 16), "bottomleft")
        else:                                               # HUD limpo: só um número no monte
            cx, cy = bx - 30, CY + CARTA_A // 2 + 34
            pygame.draw.circle(t, (10, 8, 20), (cx, cy), 17)
            pygame.draw.circle(t, (120, 110, 170), (cx, cy), 17, 2)
            texto(t, v.f_peq, str(len(p.baralho)), BRANCO, (cx, cy), sombra=False)

    def desenhar_guias(self):
        """Sinais visuais (no lugar dos textos): seta na mão = sua vez; pontinhos = esperando alguém."""
        if self.dicas or self.tip_atual:
            return
        t, p = self.tela, self.mao
        if self.estado == "humano":
            y = ALTURA - CARTA_A - 78 + math.sin(self.t * 5) * 6
            pygame.draw.polygon(t, (0, 0, 0), [(CX - 14, y - 20 + 3), (CX + 14, y - 20 + 3), (CX, y + 3)])
            pygame.draw.polygon(t, DOURADO, [(CX - 14, y - 22), (CX + 14, y - 22), (CX, y)])
        elif self.estado in ("cpu", "remoto"):
            lado = self.cfg["lados"][p.vez]
            pos = {"cima": (CX, 192), "esq": (52, CY + 148), "dir": (LARGURA - 52, CY + 148)}.get(lado)
            if pos:
                for k in range(3):
                    dy = math.sin(self.t * 7 - k * 0.9) * 5
                    pygame.draw.circle(t, DOURADO, (pos[0] - 18 + k * 18, pos[1] + dy), 5)

    def desenhar_fim(self):
        t, v, cfg = self.tela, self.vis, self.cfg
        a, b = self.mao.resultado()
        if a > b:
            titulo, cor = cfg["vitoria"], DOURADO
        elif b > a:
            titulo, cor = cfg["derrota"], (255, 120, 110)
        else:
            titulo, cor = "Empate!", BRANCO
        pulso = 1 + math.sin(self.t * 3) * 0.04
        texto(t, v.f_gde, titulo, cor, (CX, CY - 50 + math.sin(self.t * 2) * 4), escala=pulso)
        texto(t, v.f_med, cfg["linha_fim"].format(a=a, b=b), BRANCO, (CX, CY + 22))
        if self.online and self.papel == "cliente":
            rodape = "Aguardando o host reiniciar   |   ESC: sair da sala"
        elif self.online:
            rodape = "ENTER: jogar novamente (todos)   |   ESC: sair da sala"
        else:
            rodape = "ENTER: jogar novamente   |   M ou ESC: menu"
        texto(t, v.f_peq, rodape, (205, 205, 225), (CX, CY + 74))

    def desenhar_rg_res(self):
        t, v, res = self.tela, self.vis, self.rg_res
        pulso = 1 + math.sin(self.t * 3) * 0.04
        if res["venceu"]:
            titulo, cor = "META BATIDA!", DOURADO
        else:
            titulo, cor = "NÃO FOI DESTA VEZ", (255, 120, 110)
        texto(t, v.f_gde, titulo, cor, (CX, CY - 170 + math.sin(self.t * 2) * 4), escala=pulso)
        texto(t, v.f_num, f"{res['score']} / {res['meta']} pontos", BRANCO, (CX, CY - 100))
        y = CY - 50
        for rot, val, cor_l in res["linhas"]:
            texto(t, v.f_med, rot, BRANCO, (CX - 170, y), "midleft")
            texto(t, v.f_med, val, cor_l, (CX + 170, y), "midright")
            y += 40
        if res["venceu"]:
            texto(t, v.f_num, f"TOTAL  +${res['total']}", COR_DINHEIRO, (CX, y + 20))
        else:
            n = res.get("vidas_perdidas", 1)
            texto(t, v.f_med, f"Você perdeu {n} vida{'s' if n > 1 else ''}", COR_MULT, (CX, CY - 20))
            for i in range(MAX_VIDAS):
                cor_h = COR_NAIPE["copas"] if i < self.run.vidas else (70, 64, 96)
                desenhar_naipe(t, "copas", CX - 60 + i * 30, CY + 40, 24, cor_h)
        rod = "Fim da run" if self.run.fim else ("ENTER: ir para a loja" if res["venceu"] else "ENTER: tentar de novo")
        texto(t, v.f_peq, rod, (205, 205, 225), (CX, ALTURA - 60))

    def desenhar_jogo(self):
        v, t = self.vis, self.tela
        t.blit(v.fundo(self.t), (0, 0))
        self.desenhar_hud()
        self.desenhar_rotulos()
        if self.run:
            self.desenhar_curingas_hud()
        self.desenhar_cartas()
        if self.estado in ("fim", "rg_res"):
            t.blit(v.veu_escuro, (0, 0))
        self.desenhar_particulas()
        self.desenhar_guias()
        if self.mensagem and self.dicas:
            texto(t, v.f_msg, self.mensagem, BRANCO, (CX, CY + 128 + math.sin(self.t * 2.5) * 2))
        if self.aviso_txt and pygame.time.get_ticks() < self.aviso_ate:
            texto(t, v.f_msg, self.aviso_txt, DOURADO, (CX, CY - 150))
        if self.estado == "fim":
            self.desenhar_fim()
        elif self.estado == "rg_res":
            self.desenhar_rg_res()
        elif self.run and self.tip_atual is None:
            mouse = pygame.mouse.get_pos()
            for i in range(len(self.run.curingas)):
                rc = self.rect_mini(i)
                if rc.collidepoint(mouse):
                    self.desenhar_tooltip(self.run.curingas[i]["id"], (rc.centerx, rc.top - 10))

    def desenhar(self):
        if self.cena == "menu":
            self.desenhar_menu()
        elif self.cena == "mp":
            self.desenhar_mp()
        elif self.cena == "rg_mapa":
            self.desenhar_mapa()
        elif self.cena == "rg_loja":
            self.desenhar_loja()
        elif self.cena == "rg_fim":
            self.desenhar_rg_fim()
        else:
            self.desenhar_jogo()
        if self.cena in ("rg_mapa", "rg_loja", "rg_fim") and self.aviso_txt and pygame.time.get_ticks() < self.aviso_ate:
            texto(self.tela, self.vis.f_msg, self.aviso_txt, DOURADO, (CX, ALTURA - 70))
        self.desenhar_textos()
        self.desenhar_tip()
        if self.cortina > 2:                                # fade de transição
            self.veu.set_alpha(int(limitar(self.cortina, 0, 255)))
            self.tela.blit(self.veu, (0, 0))
        ox = int(random.uniform(-1, 1) * self.tremor)
        oy = int(random.uniform(-1, 1) * self.tremor)
        if ox or oy:
            self.janela.fill((0, 0, 0))
        self.janela.blit(self.tela, (ox, oy))
        pygame.display.flip()

    # ---------- loop ----------
    def evento_jogo(self, e):
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE or (e.key == pygame.K_m and not self.run):
                if self.run:
                    self.confirmar_abandono()
                else:
                    self.voltar_ao_menu()
            elif e.key == pygame.K_r and not self.run:
                self.reiniciar()
            elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self.estado == "fim":
                    self.reiniciar()
                elif self.estado == "rg_res":
                    self.rg_continuar()
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if self.estado == "rg_res":
                self.rg_continuar()
            else:
                self.clique(e.pos)

    def executar(self):
        while True:
            dt = min(self.relogio.tick(FPS) / 1000.0, 0.05)
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    self.encerrar_rede()
                    self.sair()
                if e.type == pygame.KEYDOWN and e.key == pygame.K_F1:
                    self.dicas = not self.dicas
                    continue
                if self.tip_atual:                          # com uma dica na tela, só ela recebe cliques/teclas
                    if (e.type == pygame.KEYDOWN and e.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE)) \
                            or (e.type == pygame.MOUSEBUTTONDOWN and e.button == 1):
                        self.avancar_tip()
                    continue
                if self.cena == "menu":
                    self.evento_menu(e)
                elif self.cena == "mp":
                    self.evento_mp(e)
                elif self.cena == "rg_mapa":
                    self.evento_mapa(e)
                elif self.cena == "rg_loja":
                    self.evento_loja(e)
                elif self.cena == "rg_fim":
                    self.evento_rg_fim(e)
                else:
                    self.evento_jogo(e)
            self.atualizar(dt)
            self.desenhar()


if __name__ == "__main__":
    App().executar()