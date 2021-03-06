# -*- coding: utf-8 -*-
import sys
reload(sys)
sys.setdefaultencoding('utf8')

from flask import redirect, session, url_for, render_template, \
    flash, abort, request, current_app, jsonify, make_response

from . import main, forms
from .. import db, csrf
from ..models import User, Permission, Role, Answer, Question, Vote, Comment
from ..decorators import permission_required, admin_required
from flask_login import login_required, current_user
from .forms import EditProfileForm, EditProfileAdminForm, QuestionForm, AnswerForm, CommentForm
from flask_wtf.csrf import validate_csrf, ValidationError


@main.route('/', methods=['POST', 'GET'])
def index():
    form = QuestionForm()
    if current_user.can(Permission.WRITE_ARTICLES) and form.validate_on_submit():
        q = Question(author=current_user._get_current_object(), body=form.body.data, title=form.title.data)
        db.session.add(q)
        return redirect(url_for('.index'))
    show_followed_answers = False
    if current_user.is_authenticated:
        show_followed_answers = bool(request.cookies.get('show_followed_answers', ''))
    if show_followed_answers:
        query = current_user.followed_answers
    else:
        query = Answer.query
    page = request.args.get('page', 1, type=int)
    pagination = query.order_by(Answer.timestamp.desc()).paginate(page, per_page=50, error_out=False)
    answers = pagination.items
    return render_template('index.html', form=form, page=page, answers=answers,
                           pagination=pagination, show_followed_answers=show_followed_answers)


@main.route('/all_answers')
@login_required
def show_all_answers():
    resp = make_response(redirect(url_for('.index')))
    resp.set_cookie('show_followed_answers', '', max_age=30*24*60*60)
    return resp


@main.route('/followed_answers')
@login_required
def show_followed_answers():
    resp = make_response(redirect(url_for('.index')))
    resp.set_cookie('show_followed_answers', '1', max_age=30 * 24 * 60 * 60)
    return resp


@main.route('/questions')
def questions():
    page = request.args.get('page', 1, type=int)
    pagination = Question.query.order_by(Question.timestamp.desc())\
        .paginate(page, per_page=20, error_out=False)
    qs = pagination.items
    return render_template('questions.html', page=page, questions=qs,
                           pagination=pagination)


@main.route('/question/<int:id>')
def question(id):
    the_question = Question.query.get_or_404(id)
    answers = the_question.answers.all()
    return render_template('question.html', question=the_question, answers=answers)


@main.route('/question-modify/<int:id>', methods=['POST', 'GET'])
@login_required
@permission_required(Permission.WRITE_ARTICLES)
def question_modify(id):
    the_question = Question.query.get_or_404(id)
    form = QuestionForm()
    if form.validate_on_submit():
        the_question.title = form.title.data
        the_question.body = form.body.data
        return redirect(url_for('main.question', id=id))
    form.title.data = the_question.title
    form.body.data = the_question.body
    return render_template('edit_question.html', form=form, question=the_question)


@main.route('/answer/<int:id>', methods=['POST', 'GET'])
@login_required
def answer(id):
    answer = Answer.query.get_or_404(id)
    form = CommentForm()
    if form.validate_on_submit():
        comment = Comment(body=form.body.data,
                          answer=answer,
                          author=current_user._get_current_object())
        db.session.add(comment)
        flash('评论已提交')
        return redirect(url_for('.answer', id=id))
    page = request.args.get('page', 1, type=int)
    if page == -1:
        page = (Answer.comments.count() - 1) / 20
    pagination = answer.comments.order_by(Comment.timestamp.asc()).paginate(
        page, per_page=20, error_out=False)
    comments = pagination.items
    return render_template('answer.html', answers=[answer], form=form,
                           comments=comments, pagination=pagination)


@main.route('/answer_edit/<int:id>', methods=['POST', 'GET'])
@login_required
@permission_required(Permission.WRITE_ARTICLES)
def answer_edit(id):
    the_question = Question.query.get_or_404(id)
    old_answer = the_question.answers.filter_by(answerer=current_user).first()
    form = AnswerForm()
    if form.validate_on_submit():
        if old_answer is not None:
            old_answer.body = form.body.data
            db.session.add(old_answer)
        else:
            answer = Answer(body=form.body.data, q_answer=the_question, answerer=current_user._get_current_object())
            db.session.add(answer)
        return redirect(url_for('main.question', id=id))
    if old_answer is not None:
        form.body.data = old_answer.body
    return render_template('edit_answer.html', question=the_question, form=form)


@main.route('/user/<nickname>')
def user(nickname):
    user = User.query.filter_by(nickname=nickname).first()
    if user is None:
        abort(404)

    return render_template('user.html', user=user)


@main.route('/focus/<int:id>')
@login_required
@permission_required(Permission.FOLLOW)
def focus(id):
    q = Question.query.get_or_404(id)
    if current_user.is_focus(q):
        flash('已关注此问题！')
        return redirect(url_for('.question', id=id))
    current_user.focus(q)
    flash('关注问题成功！')
    return redirect(url_for('.question', id=id))


@main.route('/unfocus/<int:id>')
@login_required
@permission_required(Permission.FOLLOW)
def unfocus(id):
    q = Question.query.get_or_404(id)
    if current_user.is_focus(q):
        current_user.unfocus(q)
        flash('取消关注成功')
        return redirect(url_for('.question', id=id))
    flash('未关注此问题')
    return redirect(url_for('.question', id=id))


@main.route('/follow/<nickname>')
@login_required
@permission_required(Permission.FOLLOW)
def follow(nickname):
    user = User.query.filter_by(nickname=nickname).first()
    if user is None:
        flash('不存在的用户！')
        return redirect(url_for('.index'))
    if current_user.is_following(user):
        flash('你已关注此用户！')
        return redirect(url_for('.user', nickname=nickname))
    current_user.follow(user)
    flash('已关注 %s' % nickname)
    return redirect(url_for('.user', nickname=nickname))


@main.route('/unfollow/<nickname>')
@login_required
@permission_required(Permission.FOLLOW)
def unfollow(nickname):
    user = User.query.filter_by(nickname=nickname).first()
    if user is None:
        flash('该用户不存在')
        return redirect(url_for('.index'))
    if not current_user.is_following(user):
        flash('你尚未关注此用户.')
        return redirect(url_for('.user', nickname=nickname))
    current_user.unfollow(user)
    flash('你已不再关注 %s.' % nickname)
    return redirect(url_for('.user', nickname=nickname))


@main.route('/followers/<nickname>')
@login_required
def followers(nickname):
    user = User.query.filter_by(nickname=nickname).first()
    if user is None:
        flash('不存在此用户')
        return redirect(url_for('.index'))
    page = request.args.get('page', 1, type=int)
    pagination = user.followers.paginate(page, per_page=20, error_out=False)
    follows = [{'user': item.follower, 'timestamp': item.timestamp}
               for item in pagination.items]
    return render_template('followers.html', user=user, title='关注了',
                           endpoint='.followers', pagination=pagination,follows=follows)


@main.route('/followed-by/<nickname>')
@login_required
def followed_by(nickname):
    user = User.query.filter_by(nickname=nickname).first()
    if user is None:
        flash('不存在此用户')
        return redirect(url_for('.index'))
    page = request.args.get('page', 1, type=int)
    pagination = user.followed.paginate(
        page, per_page=20,
        error_out=False)
    follows = [{'user': item.followed, 'timestamp': item.timestamp}
               for item in pagination.items]
    return render_template('followers.html', user=user, title='被关注',
                           endpoint='.followed_by', pagination=pagination,
                           follows=follows)


@main.route('/edit-profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = EditProfileForm()
    if form.validate_on_submit():
        current_user.name = form.name.data
        current_user.location = form.location.data
        current_user.about_me = form.about_me.data
        db.session.add(current_user)
        flash('个人信息已更新。')
        return redirect(url_for('.user', nickname=current_user.nickname))
    form.name.data = current_user.name
    form.location.data = current_user.location
    form.about_me.data = current_user.about_me
    return render_template('edit_profile.html', form=form)


@main.route('/edit-profile/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_profile_admin(id):
    user = User.query.get_or_404(id)
    form = EditProfileAdminForm(user=user)
    if form.validate_on_submit():
        user.email = form.email.data
        user.nickname = form.nickname.data
        user.confirmed = form.confirmed.data
        user.role = Role.query.get(form.role.data)
        user.name = form.name.data
        user.location = form.location.data
        user.about_me = form.about_me.data
        db.session.add(user)
        flash('信息已更新')
        return redirect(url_for('.user', nickname=user.nickname))
    form.email.data = user.email
    form.nickname.data = user.nickname
    form.confirmed.data = user.confirmed
    form.role.data = user.role_id
    form.name.data = user.name
    form.location.data = user.location
    form.about_me.data = user.about_me
    return render_template('edit_profile.html', form=form, user=user)


@main.route('/vote-post', methods=['POST'])
@csrf.exempt
# @login_required
def vote_post():
    # 如果用户未登录，返回相关信息给AJAX，手动处理重定向。
    # 如果交给@login_required自动重定向的话，
    # AJAX不能正确处理这个重定向
    if not current_user.is_authenticated:
        return jsonify({
            'status': 302,
            'location': url_for(
                'auth.login',
                next=request.referrer.replace(
                    url_for('.index', _external=True)[:-1], ''))
        })
    # 以post方式传的数据在存储在的request.form中，以get方式传输的在request.args中~~
    # 同理，csrf token认证也要手动解决重定向
    try:
        validate_csrf(request.headers.get('X-CSRFToken'))
    except ValidationError:
        return jsonify({
            'status': 400,
            'location': url_for(
                'auth.login',
                next=request.referrer.replace(
                    url_for('.index', _external=True)[:-1], ''))
        })
    answer = Answer.query.get_or_404(int(request.form.get('id')))
    if current_user.id == answer.answerer_id:
        return 'disable'
    if current_user.vote_answer(answer):
        return 'vote'
    else:
        return 'cancel'
