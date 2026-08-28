import os
import uuid
import re
import json
import logging
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
from sqlalchemy import text

# --- CONFIGURACAO PRODUCAO ELIM V9 ---
app = Flask(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def normalize_database_url(url):
    """Normaliza o valor recebido exclusivamente do ambiente do servidor."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url

# A conexao nunca possui valor padrao no codigo. O servico de hospedagem
# deve injetar DATABASE_URL como variavel de ambiente. Se ela nao existir,
# a aplicacao encerra antes de iniciar para evitar fallback inseguro.
try:
    database_uri = normalize_database_url(os.environ["DATABASE_URL"].strip())
except KeyError as exc:
    raise RuntimeError("DATABASE_URL deve ser configurada nas variaveis de ambiente do servico.") from exc

if not database_uri:
    raise RuntimeError("DATABASE_URL esta vazia nas variaveis de ambiente do servico.")

engine_options = {
    "pool_pre_ping": True,
    "pool_recycle": int(os.environ.get("DB_POOL_RECYCLE", "300")),
}
if database_uri.startswith("postgresql"):
    engine_options.update({
        "pool_size": int(os.environ.get("DB_POOL_SIZE", "5")),
        "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", "10")),
        "pool_timeout": int(os.environ.get("DB_POOL_TIMEOUT", "30")),
    })

try:
    secret_key = os.environ["SECRET_KEY"].strip()
except KeyError as exc:
    raise RuntimeError("SECRET_KEY deve ser configurada nas variaveis de ambiente do servico.") from exc

if not secret_key:
    raise RuntimeError("SECRET_KEY esta vazia nas variaveis de ambiente do servico.")

app.config.update(
    SECRET_KEY=secret_key,
    SQLALCHEMY_DATABASE_URI=database_uri,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SQLALCHEMY_ENGINE_OPTIONS=engine_options,
    JSON_AS_ASCII=False,
    MAX_CONTENT_LENGTH=100 * 1024 * 1024,
    UPLOAD_FOLDER=UPLOAD_FOLDER,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "true").lower() == "true",
)

# Logging para producao
if not app.debug:
    gunicorn_logger = logging.getLogger('gunicorn.error')
    if gunicorn_logger.handlers:
        app.logger.handlers = gunicorn_logger.handlers
        app.logger.setLevel(gunicorn_logger.level)
    else:
        logging.basicConfig(level=logging.INFO)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Sessao expirada ou acesso restrito."
login_manager.login_message_category = "warning"
CORS(app)

# --- MODELOS ---

class User(db.Model, UserMixin):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="aluno", nullable=False, index=True)
    xp = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    is_approved = db.Column(db.Boolean, default=False, index=True)
    last_login = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    logs = db.relationship('LogAtividade', backref='owner', cascade="all, delete-orphan", lazy='dynamic')
    progresso = db.relationship('ProgressoAula', backref='estudante', lazy='dynamic', cascade="all, delete-orphan")
    notificacoes = db.relationship('Notification', backref='user', lazy='dynamic', cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def nivel(self):
        return (self.xp // 1000) + 1

    @property
    def xp_no_nivel(self):
        return self.xp % 1000

class Aula(db.Model):
    __tablename__ = "aulas"
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True)
    descricao = db.Column(db.Text)
    url_video = db.Column(db.String(500))
    categoria = db.Column(db.String(100), index=True)
    minutos_estimados = db.Column(db.Integer, default=0)
    xp_recompensa = db.Column(db.Integer, default=100)
    quiz_data = db.Column(db.JSON)
    status = db.Column(db.String(20), default="publicado")
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    criado_por = db.Column(db.Integer, db.ForeignKey('users.id'))

class ProgressoAula(db.Model):
    __tablename__ = "progresso_aulas"
    __table_args__ = (db.UniqueConstraint("user_id", "aula_id", name="uq_progresso_user_aula"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    aula_id = db.Column(db.Integer, db.ForeignKey('aulas.id'), index=True)
    concluido = db.Column(db.Boolean, default=False)
    nota_quiz = db.Column(db.Float, nullable=True)
    data_conclusao = db.Column(db.DateTime, default=datetime.utcnow)

class LogAtividade(db.Model):
    __tablename__ = "logs_atividades"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    acao = db.Column(db.String(255))
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)

class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    mensagem = db.Column(db.String(255))
    lida = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

class Feedback(db.Model):
    __tablename__ = "feedbacks"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    nome = db.Column(db.String(100))
    email = db.Column(db.String(120))
    tipo = db.Column(db.String(50), default="sugestao")
    mensagem = db.Column(db.Text, nullable=False)
    avaliacao = db.Column(db.Integer, default=5)
    data_envio = db.Column(db.DateTime, default=datetime.utcnow)
    lido = db.Column(db.Boolean, default=False)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# --- UTILITARIOS ---

def registrar_log(acao):
    if current_user and current_user.is_authenticated:
        log = LogAtividade(
            user_id=current_user.id,
            acao=acao,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        db.session.add(log)
        db.session.commit()

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            # Normaliza 'docente' para 'professor'
            user_role = current_user.role
            if user_role == 'docente':
                user_role = 'professor'
            normalized_roles = [r if r != 'docente' else 'professor' for r in roles]
            if user_role not in normalized_roles:
                if request.is_json:
                    return jsonify({"success": False, "error": "Acesso Negado"}), 403
                flash("Area restrita. Voce nao possui as permissoes necessarias.", "danger")
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def extrair_id_youtube(url):
    if not url:
        return ""
    regex = r'(?:v=|\/|be\/)([0-9A-Za-z_-]{11}).*'
    match = re.search(regex, url)
    return match.group(1) if match else ""

def gerar_slug(titulo):
    base = titulo.lower().strip()
    base = re.sub(r'\s+', '-', base)
    base = re.sub(r'[^a-z0-9-]', '', base)
    return f"{base}-{str(uuid.uuid4())[:5]}"

# --- ERROR HANDLERS ---

@app.errorhandler(404)
def not_found(e):
    if request.is_json:
        return jsonify({"success": False, "error": "Recurso nao encontrado"}), 404
    return render_template("index.html"), 404

@app.errorhandler(500)
def server_error(e):
    db.session.rollback()
    if request.is_json:
        return jsonify({"success": False, "error": "Erro interno do servidor"}), 500
    return "Erro interno", 500

# --- ROTAS PRINCIPAIS ---

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/dashboard")
@login_required
def dashboard():
    aulas_recentes = (
        Aula.query.filter_by(status="publicado")
        .order_by(Aula.data_criacao.desc())
        .limit(6)
        .all()
    )
    aulas_count = Aula.query.filter_by(status="publicado").count()
    concluidas = current_user.progresso.filter_by(concluido=True).count()
    progresso_pct = round((concluidas / aulas_count) * 100) if aulas_count else 0

    stats = {
        "aulas_count": aulas_count,
        "meu_progresso": concluidas,
        "progresso_pct": progresso_pct,
        "xp": current_user.xp,
        "nivel": current_user.nivel,
        "xp_no_nivel": current_user.xp_no_nivel,
        "atividades": (
            LogAtividade.query.filter_by(user_id=current_user.id)
            .order_by(LogAtividade.timestamp.desc())
            .limit(6)
            .all()
        ),
        "aulas": aulas_recentes,
        "notificacoes_nao_lidas": Notification.query.filter_by(user_id=current_user.id, lida=False).count(),
        "alunos_count": User.query.filter_by(role="aluno", is_approved=True).count() if current_user.role in ["admin", "professor", "docente"] else None,
        "pendentes_count": User.query.filter_by(is_approved=False).count() if current_user.role == "admin" else None,
    }
    return render_template("home.html", **stats)

@app.route("/aulas")
@login_required
def lista_aulas():
    categoria = request.args.get('cat')
    query = Aula.query.filter_by(status="publicado")
    if categoria:
        query = query.filter_by(categoria=categoria)
    aulas = query.order_by(Aula.data_criacao.desc()).all()
    return render_template("aulas_lista.html", aulas=aulas)

@app.route("/aula/<slug>")
@login_required
def ver_aula(slug):
    aula = Aula.query.filter_by(slug=slug).first_or_404()
    progresso = ProgressoAula.query.filter_by(user_id=current_user.id, aula_id=aula.id).first()
    return render_template("aula.html", aula=aula, progresso=progresso)

@app.route("/aula/<slug>/desafio")
@login_required
def ver_desafio(slug):
    aula = Aula.query.filter_by(slug=slug).first_or_404()
    if not aula.quiz_data:
        flash("Esta aula nao possui desafio.", "info")
        return redirect(url_for('ver_aula', slug=slug))
    progresso = ProgressoAula.query.filter_by(user_id=current_user.id, aula_id=aula.id).first()
    return render_template("desafio.html", aula=aula, progresso=progresso)

@app.route("/api/aulas/concluir", methods=['POST'])
@login_required
def concluir_aula():
    data = request.get_json()
    aula_id = data.get('aula_id')
    nota = data.get('nota', 0)

    aula = db.session.get(Aula, aula_id)
    if not aula:
        return jsonify({"success": False, "message": "Aula nao encontrada"}), 404

    progresso = ProgressoAula.query.filter_by(user_id=current_user.id, aula_id=aula.id).first()

    if not progresso:
        novo_progresso = ProgressoAula(
            user_id=current_user.id,
            aula_id=aula.id,
            concluido=True,
            nota_quiz=nota
        )
        current_user.xp += aula.xp_recompensa
        db.session.add(novo_progresso)
        msg = f"Concluiu a aula: {aula.titulo}"
    else:
        progresso.nota_quiz = max(progresso.nota_quiz or 0, nota)
        msg = f"Refez o quiz da aula: {aula.titulo}"

    db.session.commit()
    registrar_log(msg)
    return jsonify({"success": True, "new_xp": current_user.xp, "nivel": current_user.nivel})

# --- FEEDBACK ---

@app.route("/feedback", methods=['GET', 'POST'])
def feedback():
    if request.method == 'POST':
        data = request.get_json() if request.is_json else request.form

        novo_feedback = Feedback(
            user_id=current_user.id if current_user.is_authenticated else None,
            nome=data.get('nome', current_user.name if current_user.is_authenticated else 'Anonimo'),
            email=data.get('email', current_user.email if current_user.is_authenticated else ''),
            tipo=data.get('tipo', 'sugestao'),
            mensagem=data.get('mensagem'),
            avaliacao=int(data.get('avaliacao', 5))
        )
        db.session.add(novo_feedback)
        db.session.commit()

        if request.is_json:
            return jsonify({"success": True, "message": "Feedback enviado com sucesso!"})
        flash("Obrigado pelo seu feedback!", "success")
        return redirect(url_for('feedback'))

    return render_template("feedback.html")

@app.route("/admin/feedbacks")
@role_required('admin')
def lista_feedbacks():
    feedbacks = Feedback.query.order_by(Feedback.data_envio.desc()).all()
    return render_template("admin_feedbacks.html", feedbacks=feedbacks)

# --- CMS / UPLOAD ---

@app.route("/upload")
@role_required('admin', 'professor', 'docente')
def upload():
    return render_template("upload.html")

@app.route("/api/aulas/cadastrar", methods=['POST'])
@role_required('admin', 'professor', 'docente')
def api_cadastrar_aula():
    data = request.get_json()
    if not data or not data.get('nome'):
        return jsonify({"success": False, "message": "O titulo da aula e obrigatorio"}), 400

    try:
        slug = gerar_slug(data.get('nome'))

        video_id = extrair_id_youtube(data.get('url_video'))
        if not video_id:
            return jsonify({"success": False, "message": "Link do YouTube invalido"}), 400

        nova_aula = Aula(
            titulo=data.get('nome'),
            slug=slug,
            descricao=data.get('descricao'),
            url_video=video_id,
            categoria=data.get('categoria', 'Geral'),
            minutos_estimados=int(data.get('tempo', 0)),
            xp_recompensa=int(data.get('xp', 100)),
            quiz_data=data.get('quiz'),
            criado_por=current_user.id
        )

        db.session.add(nova_aula)
        db.session.commit()
        registrar_log(f"Publicou nova aula: {nova_aula.titulo}")

        return jsonify({"success": True, "message": "Aula publicada!", "redirect": "/aulas"})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erro ao cadastrar aula: {str(e)}")
        return jsonify({"success": False, "message": f"Erro interno: {str(e)}"}), 500

# --- API PARA PAINEL PROFESSOR (LEGADO/INTEGRADO) ---

@app.route("/api/studies", methods=['GET'])
@login_required
def api_studies():
    """Retorna aulas publicadas em formato simplificado para consumo via API."""
    aulas = Aula.query.filter_by(status="publicado").order_by(Aula.data_criacao.desc()).all()
    result = []
    for a in aulas:
        result.append({
            "id": a.id,
            "title": a.titulo,
            "category": a.categoria or "Geral",
            "content": a.descricao or "Conteudo teologico exclusivo.",
            "date": a.data_criacao.strftime('%d/%m/%Y') if a.data_criacao else "",
            "slug": a.slug,
            "video_id": a.url_video
        })
    return jsonify(result)

@app.route("/api/studies/create", methods=['POST'])
@role_required('admin', 'professor', 'docente')
def api_studies_create():
    """Cria aula via JSON para o fluxo de publicacao simplificada."""
    data = request.get_json()
    if not data or not data.get('title'):
        return jsonify({"success": False, "message": "Titulo obrigatorio"}), 400
    try:
        slug = gerar_slug(data.get('title'))
        nova = Aula(
            titulo=data.get('title'),
            slug=slug,
            descricao=data.get('content', ''),
            categoria=data.get('category', 'Geral'),
            url_video='',
            minutos_estimados=0,
            xp_recompensa=50,
            quiz_data=None,
            criado_por=current_user.id
        )
        db.session.add(nova)
        db.session.commit()
        registrar_log(f"Publicou estudo via painel professor: {nova.titulo}")
        return jsonify({"success": True, "message": "Conteudo publicado!"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/professor/cadastrar-aluno", methods=['POST'])
@role_required('admin', 'professor', 'docente')
def api_cadastrar_aluno():
    """Cadastra aluno via painel professor."""
    data = request.get_json()
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    if not name or not email:
        return jsonify({"success": False, "message": "Nome e email obrigatorios"}), 400
    if len(password) < 8:
        return jsonify({"success": False, "message": "Informe uma senha com pelo menos 8 caracteres"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"success": False, "message": "Email ja cadastrado"}), 409
    try:
        novo = User(name=name, email=email, role="aluno", is_approved=True)
        novo.set_password(password)
        db.session.add(novo)
        db.session.commit()
        registrar_log(f"Cadastrou aluno via painel: {email}")
        return jsonify({"success": True, "message": "Aluno matriculado!"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/professor/alunos", methods=["GET"])
@role_required("admin", "professor", "docente")
def api_professor_alunos():
    alunos = (
        User.query.filter_by(role="aluno", is_approved=True)
        .order_by(User.name.asc())
        .all()
    )
    return jsonify([
        {
            "id": aluno.id,
            "name": aluno.name,
            "email": aluno.email,
            "xp": aluno.xp,
            "nivel": aluno.nivel,
            "created_at": aluno.created_at.strftime("%d/%m/%Y") if aluno.created_at else "",
        }
        for aluno in alunos
    ])

@app.route("/estudo/<int:id>")
@login_required
def ver_estudo(id):
    aula = db.session.get(Aula, id)
    if not aula:
        abort(404)
    return redirect(url_for('ver_aula', slug=aula.slug))

# --- ADMINISTRACAO ---

@app.route("/admin/usuarios")
@role_required('admin')
def gerenciar_usuarios():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin_users.html", users=users)

@app.route("/admin/aprovacoes")
@role_required('admin')
def lista_aprovacoes():
    pedidos = User.query.filter_by(is_approved=False).order_by(User.created_at.desc()).all()
    professores = User.query.filter_by(role='professor', is_approved=True).all()
    alunos = User.query.filter_by(role='aluno', is_approved=True).order_by(User.name).all()
    aulas = Aula.query.order_by(Aula.data_criacao.desc()).all()
    users = User.query.order_by(User.created_at.desc()).all()  # CORRECAO: para tab usuarios
    return render_template("aceitarpedidos.html", pedidos=pedidos, professores=professores, alunos=alunos, aulas=aulas, users=users)

@app.route("/api/admin/aprovar/<int:user_id>", methods=['POST'])
@role_required('admin')
def api_aprovar_usuario(user_id):
    user = db.get_or_404(User, user_id)
    data = request.get_json() or {}
    try:
        user.is_approved = True
        cargo = data.get('cargo', 'aluno')
        if cargo in ['aluno', 'professor', 'admin', 'docente']:
            user.role = cargo
        notif = Notification(user_id=user.id, mensagem="Parabens! Sua conta foi aprovada.")
        db.session.add(notif)
        db.session.commit()
        registrar_log(f"Aprovou usuario: {user.email} como {user.role}")
        return jsonify({"success": True, "message": "Usuario aprovado com sucesso.", "role": user.role})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/admin/rejeitar/<int:user_id>", methods=['POST'])
@role_required('admin')
def api_rejeitar_usuario(user_id):
    user = db.get_or_404(User, user_id)
    try:
        db.session.delete(user)
        db.session.commit()
        registrar_log(f"Rejeitou e removeu usuario: {user.email}")
        return jsonify({"success": True, "message": "Usuario removido."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

# --- AUTENTICACAO ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        data = request.get_json() if request.is_json else request.form
        email = data.get('email', '').lower().strip()
        user = User.query.filter_by(email=email).first()

        if user and user.check_password(data.get('password')):
            if not user.is_approved:
                return jsonify({"success": False, "error": "Sua conta ainda nao foi aprovada pelo administrador."}), 401

            login_user(user, remember=True)
            user.last_login = datetime.utcnow()
            db.session.commit()
            registrar_log("Login no sistema")

            if request.is_json:
                return jsonify({"success": True, "redirect": url_for('dashboard'), "role": user.role, "name": user.name})
            return redirect(url_for('dashboard'))

        if request.is_json:
            return jsonify({"success": False, "error": "E-mail ou senha incorretos."}), 401
        flash("E-mail ou senha incorretos.", "danger")

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        data = request.get_json() if request.is_json else request.form
        email = data.get('email', '').lower().strip()
        name = data.get('name', '').strip()

        if not name or not email or not data.get('password'):
            if request.is_json:
                return jsonify({"success": False, "error": "Preencha todos os campos."}), 400
            flash("Preencha todos os campos.", "danger")
            return render_template('register.html')

        if User.query.filter_by(email=email).first():
            if request.is_json:
                return jsonify({"success": False, "error": "Este e-mail ja esta em uso."}), 409
            flash("Este e-mail ja esta em uso.", "danger")
            return render_template('register.html')

        novo_user = User(name=name, email=email, role="aluno")
        novo_user.set_password(data.get('password'))
        db.session.add(novo_user)
        db.session.commit()

        if request.is_json:
            return jsonify({"success": True, "message": "Cadastro realizado! Aguarde a aprovacao do administrador."})
        flash("Cadastro realizado! Aguarde a aprovacao.", "success")
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route("/logout")
@login_required
def logout():
    registrar_log("Saiu do sistema")
    logout_user()
    return redirect(url_for('login'))

# Alias para compatibilidade com paineis legado
@app.route("/api/auth/logout", methods=['POST', 'GET'])
@login_required
def api_logout():
    registrar_log("Saiu do sistema via API")
    logout_user()
    return jsonify({"success": True, "redirect": "/login"})

# --- PERFIL ---

@app.route("/perfil")
@login_required
def perfil():
    return render_template("perfil.html", user=current_user)

@app.route("/api/perfil/atualizar", methods=['POST'])
@login_required
def api_atualizar_perfil():
    data = request.get_json()
    try:
        if 'email' in data or 'new_password' in data:
            if not current_user.check_password(data.get('current_password')):
                return jsonify({"success": False, "message": "Senha atual incorreta."}), 401

        if 'name' in data:
            current_user.name = data.get('name').strip()
        if 'email' in data:
            current_user.email = data.get('email').lower().strip()
        if 'new_password' in data and data.get('new_password'):
            current_user.set_password(data.get('new_password'))

        db.session.commit()
        registrar_log("Atualizou dados do perfil")
        return jsonify({"success": True, "message": "Perfil atualizado com sucesso!"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

# --- NOTIFICACOES ---

@app.route("/api/notificacoes")
@login_required
def api_notificacoes():
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(10).all()
    return jsonify([{"id": n.id, "mensagem": n.mensagem, "lida": n.lida, "data": n.created_at.isoformat()} for n in notifs])

@app.route("/api/notificacoes/lidas", methods=['POST'])
@login_required
def api_marcar_notificacoes():
    Notification.query.filter_by(user_id=current_user.id, lida=False).update({"lida": True})
    db.session.commit()
    return jsonify({"success": True})

# --- SAUDE / OPERACAO ---

@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok", "service": "itel-elim"})

@app.route("/readyz")
def readyz():
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify({"status": "ready", "database": "postgresql"})
    except Exception:
        db.session.rollback()
        return jsonify({"status": "not_ready", "database": "unavailable"}), 503

# --- SETUP ---

def setup():
    """Cria tabelas e, opcionalmente, o primeiro administrador via variaveis de ambiente."""
    db.create_all()

    admin_email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "")
    admin_name = os.environ.get("ADMIN_NAME", "Administrador")

    if admin_email and admin_password and not User.query.filter_by(email=admin_email).first():
        admin = User(name=admin_name, email=admin_email, role="admin", is_approved=True)
        admin.set_password(admin_password)
        db.session.add(admin)
        db.session.commit()
        app.logger.info("Administrador inicial criado via variaveis de ambiente.")

if os.environ.get("AUTO_CREATE_DB", "true").lower() == "true":
    with app.app_context():
        setup()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
