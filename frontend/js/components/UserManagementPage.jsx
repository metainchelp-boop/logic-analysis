window.UserManagementPage = function UserManagementPage(props) {
  var useState = React.useState;
  var useEffect = React.useEffect;

  var currentUser = props.currentUser;
  var token = props.token;

  var _useState = useState([]);
  var users = _useState[0];
  var setUsers = _useState[1];

  var _useState2 = useState(false);
  var showModal = _useState2[0];
  var setShowModal = _useState2[1];

  var _useState3 = useState(null);
  var editingUser = _useState3[0];
  var setEditingUser = _useState3[1];

  var _useState4 = useState({ username: '', name: '', password: '', role: 'viewer' });
  var formData = _useState4[0];
  var setFormData = _useState4[1];

  var _useState5 = useState('');
  var message = _useState5[0];
  var setMessage = _useState5[1];

  // Fetch users on mount
  useEffect(function() {
    fetchUsers();
  }, []);

  var fetchUsers = function() {
    fetch('/api/auth/users', {
      method: 'GET',
      headers: { 'Authorization': 'Bearer ' + token }
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      setUsers(data.users || []);
      setMessage('');
    })
    .catch(function(e) {
      setMessage('사용자 조회 실패: ' + e.message);
    });
  };

  var handleOpenModal = function(user) {
    if (user) {
      setEditingUser(user);
      setFormData({ username: user.username, name: user.name, password: '', role: user.role });
    } else {
      setEditingUser(null);
      setFormData({ username: '', name: '', password: '', role: 'viewer' });
    }
    setShowModal(true);
  };

  var handleCloseModal = function() {
    setShowModal(false);
    setEditingUser(null);
    setFormData({ username: '', name: '', password: '', role: 'viewer' });
  };

  var handleSaveUser = function() {
    if (!formData.username || !formData.name) {
      setMessage('아이디와 이름을 입력하세요.');
      return;
    }

    var url = editingUser ? '/api/auth/users/' + editingUser.id : '/api/auth/users';
    var method = editingUser ? 'PUT' : 'POST';
    var body = {
      username: formData.username,
      name: formData.name,
      role: formData.role
    };

    if (formData.password) {
      body.password = formData.password;
    }

    fetch(url, {
      method: method,
      headers: {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(body)
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      setMessage(editingUser ? '사용자 수정 완료' : '사용자 추가 완료');
      handleCloseModal();
      fetchUsers();
    })
    .catch(function(e) {
      setMessage('저장 실패: ' + e.message);
    });
  };

  var handleDeleteUser = function(userId, username) {
    if (userId === currentUser.id) {
      setMessage('자신의 계정은 삭제할 수 없습니다.');
      return;
    }

    if (!window.confirm(username + ' 사용자를 삭제하시겠습니까?')) return;

    fetch('/api/auth/users/' + userId, {
      method: 'DELETE',
      headers: { 'Authorization': 'Bearer ' + token }
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      setMessage('사용자 삭제 완료');
      fetchUsers();
    })
    .catch(function(e) {
      setMessage('삭제 실패: ' + e.message);
    });
  };

  var getRoleBadge = function(role) {
    var roleMap = { admin: '관리자', manager: '매니저', viewer: '뷰어' };
    var roleColors = { admin: '#8B5CF6', manager: '#3B82F6', viewer: '#9CA3AF' };
    return React.createElement('span', {
      style: {
        backgroundColor: roleColors[role],
        color: 'white',
        padding: '4px 12px',
        borderRadius: '12px',
        fontSize: '12px',
        fontWeight: 'bold'
      }
    }, roleMap[role] || role);
  };

  var getStatusBadge = function(status) {
    var isActive = status === 'active';
    return React.createElement('span', {
      style: {
        backgroundColor: isActive ? '#10B981' : '#EF4444',
        color: 'white',
        padding: '4px 12px',
        borderRadius: '12px',
        fontSize: '12px'
      }
    }, isActive ? '활성' : '비활성');
  };

  return React.createElement('div', { style: { padding: '20px', fontFamily: 'sans-serif' } },
    React.createElement('div', { style: { marginBottom: '20px' } },
      React.createElement('h1', { style: { color: '#6B21A8', marginBottom: '20px' } }, '👥 직원 관리'),
      React.createElement('button', {
        onClick: function() { handleOpenModal(null); },
        style: {
          backgroundColor: '#8B5CF6',
          color: 'white',
          border: 'none',
          padding: '10px 20px',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '14px',
          fontWeight: 'bold'
        }
      }, '새 직원 추가')
    ),

    message && React.createElement('div', {
      style: {
        backgroundColor: '#F0F9FF',
        border: '1px solid #8B5CF6',
        color: '#6B21A8',
        padding: '12px',
        borderRadius: '6px',
        marginBottom: '20px',
        fontSize: '14px'
      }
    }, message),

    React.createElement('div', {
      style: {
        overflowX: 'auto',
        backgroundColor: 'white',
        borderRadius: '8px',
        boxShadow: '0 1px 3px rgba(0,0,0,0.1)'
      }
    },
      React.createElement('table', {
        style: {
          width: '100%',
          borderCollapse: 'collapse',
          fontSize: '14px'
        }
      },
        React.createElement('thead', {},
          React.createElement('tr', { style: { backgroundColor: '#F3E8FF', borderBottom: '2px solid #8B5CF6' } },
            React.createElement('th', { style: { padding: '12px', textAlign: 'left', fontWeight: 'bold', color: '#6B21A8' } }, '아이디'),
            React.createElement('th', { style: { padding: '12px', textAlign: 'left', fontWeight: 'bold', color: '#6B21A8' } }, '이름'),
            React.createElement('th', { style: { padding: '12px', textAlign: 'left', fontWeight: 'bold', color: '#6B21A8' } }, '역할'),
            React.createElement('th', { style: { padding: '12px', textAlign: 'left', fontWeight: 'bold', color: '#6B21A8' } }, '상태'),
            React.createElement('th', { style: { padding: '12px', textAlign: 'left', fontWeight: 'bold', color: '#6B21A8' } }, '등록일'),
            React.createElement('th', { style: { padding: '12px', textAlign: 'left', fontWeight: 'bold', color: '#6B21A8' } }, '액션')
          )
        ),
        React.createElement('tbody', {},
          users.map(function(user, idx) {
            return React.createElement('tr', {
              key: user.id,
              style: {
                backgroundColor: idx % 2 === 0 ? 'white' : '#F9F5FF',
                borderBottom: '1px solid #E9D5FF'
              }
            },
              React.createElement('td', { style: { padding: '12px' } }, user.username),
              React.createElement('td', { style: { padding: '12px' } }, user.name),
              React.createElement('td', { style: { padding: '12px' } }, getRoleBadge(user.role)),
              React.createElement('td', { style: { padding: '12px' } }, getStatusBadge(user.status || 'active')),
              React.createElement('td', { style: { padding: '12px', fontSize: '12px', color: '#666' } }, new Date(user.createdAt).toLocaleDateString('ko-KR')),
              React.createElement('td', { style: { padding: '12px' } },
                React.createElement('button', {
                  onClick: function() { handleOpenModal(user); },
                  style: {
                    backgroundColor: '#8B5CF6',
                    color: 'white',
                    border: 'none',
                    padding: '6px 12px',
                    borderRadius: '4px',
                    cursor: 'pointer',
                    fontSize: '12px',
                    marginRight: '6px'
                  }
                }, '수정'),
                user.id !== currentUser.id && React.createElement('button', {
                  onClick: function() { handleDeleteUser(user.id, user.username); },
                  style: {
                    backgroundColor: '#EF4444',
                    color: 'white',
                    border: 'none',
                    padding: '6px 12px',
                    borderRadius: '4px',
                    cursor: 'pointer',
                    fontSize: '12px'
                  }
                }, '삭제')
              )
            );
          })
        )
      )
    ),

    showModal && React.createElement('div', {
      style: {
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(0,0,0,0.5)',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        zIndex: 1000
      }
    },
      React.createElement('div', {
        style: {
          backgroundColor: 'white',
          padding: '24px',
          borderRadius: '8px',
          width: '90%',
          maxWidth: '400px',
          boxShadow: '0 10px 25px rgba(0,0,0,0.2)'
        }
      },
        React.createElement('h2', { style: { color: '#6B21A8', marginBottom: '16px' } }, editingUser ? '직원 수정' : '새 직원 추가'),
        React.createElement('div', { style: { marginBottom: '12px' } },
          React.createElement('label', { style: { display: 'block', fontSize: '12px', fontWeight: 'bold', color: '#666', marginBottom: '4px' } }, '아이디'),
          React.createElement('input', {
            type: 'text',
            value: formData.username,
            onChange: function(e) { setFormData(Object.assign({}, formData, { username: e.target.value })); },
            disabled: !!editingUser,
            style: {
              width: '100%',
              padding: '8px',
              border: '1px solid #D8B4FE',
              borderRadius: '4px',
              boxSizing: 'border-box',
              opacity: editingUser ? 0.6 : 1
            }
          })
        ),
        React.createElement('div', { style: { marginBottom: '12px' } },
          React.createElement('label', { style: { display: 'block', fontSize: '12px', fontWeight: 'bold', color: '#666', marginBottom: '4px' } }, '이름'),
          React.createElement('input', {
            type: 'text',
            value: formData.name,
            onChange: function(e) { setFormData(Object.assign({}, formData, { name: e.target.value })); },
            style: {
              width: '100%',
              padding: '8px',
              border: '1px solid #D8B4FE',
              borderRadius: '4px',
              boxSizing: 'border-box'
            }
          })
        ),
        !editingUser && React.createElement('div', { style: { marginBottom: '12px' } },
          React.createElement('label', { style: { display: 'block', fontSize: '12px', fontWeight: 'bold', color: '#666', marginBottom: '4px' } }, '비밀번호'),
          React.createElement('input', {
            type: 'password',
            value: formData.password,
            onChange: function(e) { setFormData(Object.assign({}, formData, { password: e.target.value })); },
            style: {
              width: '100%',
              padding: '8px',
              border: '1px solid #D8B4FE',
              borderRadius: '4px',
              boxSizing: 'border-box'
            }
          })
        ),
        editingUser && React.createElement('div', { style: { marginBottom: '12px' } },
          React.createElement('label', { style: { display: 'block', fontSize: '12px', fontWeight: 'bold', color: '#666', marginBottom: '4px' } }, '새 비밀번호 (선택)'),
          React.createElement('input', {
            type: 'password',
            value: formData.password,
            onChange: function(e) { setFormData(Object.assign({}, formData, { password: e.target.value })); },
            style: {
              width: '100%',
              padding: '8px',
              border: '1px solid #D8B4FE',
              borderRadius: '4px',
              boxSizing: 'border-box'
            }
          })
        ),
        React.createElement('div', { style: { marginBottom: '16px' } },
          React.createElement('label', { style: { display: 'block', fontSize: '12px', fontWeight: 'bold', color: '#666', marginBottom: '4px' } }, '역할'),
          React.createElement('select', {
            value: formData.role,
            onChange: function(e) { setFormData(Object.assign({}, formData, { role: e.target.value })); },
            style: {
              width: '100%',
              padding: '8px',
              border: '1px solid #D8B4FE',
              borderRadius: '4px',
              boxSizing: 'border-box'
            }
          },
            React.createElement('option', { value: 'viewer' }, '뷰어'),
            React.createElement('option', { value: 'manager' }, '매니저'),
            React.createElement('option', { value: 'admin' }, '관리자')
          )
        ),
        React.createElement('div', { style: { display: 'flex', gap: '8px', justifyContent: 'flex-end' } },
          React.createElement('button', {
            onClick: handleCloseModal,
            style: {
              backgroundColor: '#E9D5FF',
              color: '#6B21A8',
              border: 'none',
              padding: '10px 20px',
              borderRadius: '4px',
              cursor: 'pointer',
              fontWeight: 'bold'
            }
          }, '취소'),
          React.createElement('button', {
            onClick: handleSaveUser,
            style: {
              backgroundColor: '#8B5CF6',
              color: 'white',
              border: 'none',
              padding: '10px 20px',
              borderRadius: '4px',
              cursor: 'pointer',
              fontWeight: 'bold'
            }
          }, '저장')
        )
      )
    )
  );
};
