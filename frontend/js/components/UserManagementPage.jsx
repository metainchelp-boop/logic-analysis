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

  var _useState6 = useState(null);
  var expandedUserId = _useState6[0];
  var setExpandedUserId = _useState6[1];

  var _useState7 = useState([]);
  var loginLogs = _useState7[0];
  var setLoginLogs = _useState7[1];

  var _useState8 = useState(false);
  var logsLoading = _useState8[0];
  var setLogsLoading = _useState8[1];

  var _useState9 = useState({});
  var analysisCounts = _useState9[0];
  var setAnalysisCounts = _useState9[1];

  var _useState10 = useState('all');
  var roleFilter = _useState10[0];
  var setRoleFilter = _useState10[1];

  // Fetch users + analysis counts on mount
  useEffect(function() {
    fetchUsers();
    fetchAnalysisCounts();
  }, []);

  var toggleLoginLogs = function(userId) {
    if (expandedUserId === userId) {
      setExpandedUserId(null);
      setLoginLogs([]);
      return;
    }
    setExpandedUserId(userId);
    setLogsLoading(true);
    setLoginLogs([]);
    api.get('/auth/users/' + userId + '/login-logs?days=7')
    .then(function(data) {
      if (data.success) setLoginLogs(data.data || []);
      setLogsLoading(false);
    })
    .catch(function() { setLogsLoading(false); });
  };

  var fetchAnalysisCounts = function() {
    api.get('/auth/users/analysis-counts')
    .then(function(data) {
      if (data.success) setAnalysisCounts(data.data || {});
    })
    .catch(function() {});
  };

  var fetchUsers = function() {
    api.get('/auth/users')
    .then(function(data) {
      // 백엔드가 배열을 직접 반환하므로 배열/객체 모두 처리
      var userList = Array.isArray(data) ? data : (data.users || []);
      setUsers(userList);
      setMessage('');
    })
    .catch(function(e) {
      setMessage('사용자 조회 실패: ' + (e.message || '네트워크 오류'));
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

    // 신규 등록 시 비밀번호 필수 검증
    if (!editingUser && (!formData.password || formData.password.length < 6)) {
      setMessage('비밀번호를 6자 이상 입력하세요.');
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

    var apiCall = editingUser
      ? api.put('/auth/users/' + editingUser.id, body)
      : api.post('/auth/users', body);

    apiCall
    .then(function(data) {
      if (data && data.success === false) {
        setMessage('저장 실패: ' + (data.detail || '알 수 없는 오류'));
        return;
      }
      // 수정 모드에서 비밀번호가 입력된 경우 → 비밀번호 리셋 API 추가 호출
      if (editingUser && formData.password && formData.password.length >= 6) {
        api.put('/auth/users/' + editingUser.id + '/reset-password', { new_password: formData.password })
        .then(function(pwRes) {
          if (pwRes && pwRes.success) {
            setMessage('사용자 수정 + 비밀번호 변경 완료');
          } else {
            setMessage('사용자 수정 완료 (비밀번호 변경 실패: ' + (pwRes.detail || '오류') + ')');
          }
          handleCloseModal();
          fetchUsers();
        }).catch(function() {
          setMessage('사용자 수정 완료 (비밀번호 변경 실패)');
          handleCloseModal();
          fetchUsers();
        });
        return;
      }
      setMessage(editingUser ? '사용자 수정 완료' : '사용자 추가 완료');
      handleCloseModal();
      fetchUsers();
    })
    .catch(function(e) {
      setMessage('저장 실패: ' + (e.message || '네트워크 오류'));
    });
  };

  var handleDeleteUser = function(userId, username) {
    if (userId === currentUser.id) {
      setMessage('자신의 계정은 삭제할 수 없습니다.');
      return;
    }

    if (!window.confirm(username + ' 사용자를 삭제하시겠습니까?')) return;

    api.del('/auth/users/' + userId)
    .then(function(data) {
      if (data && data.success === false) {
        setMessage('삭제 실패: ' + (data.detail || '알 수 없는 오류'));
        return;
      }
      setMessage('사용자 삭제 완료');
      fetchUsers();
    })
    .catch(function(e) {
      setMessage('삭제 실패: ' + (e.message || '네트워크 오류'));
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

    /* 권한별 필터 탭 */
    React.createElement('div', { style: { display: 'flex', gap: '8px', marginBottom: '16px', flexWrap: 'wrap' } },
      [
        { key: 'all', label: '전체', color: '#6B21A8' },
        { key: 'admin', label: '관리자', color: '#8B5CF6' },
        { key: 'manager', label: '매니저', color: '#3B82F6' },
        { key: 'viewer', label: '뷰어', color: '#9CA3AF' }
      ].map(function(tab) {
        var isActive = roleFilter === tab.key;
        var count = tab.key === 'all' ? users.length : users.filter(function(u) { return u.role === tab.key; }).length;
        return React.createElement('button', {
          key: tab.key,
          onClick: function() { setRoleFilter(tab.key); },
          style: {
            padding: '8px 20px',
            borderRadius: '8px',
            border: isActive ? '2px solid ' + tab.color : '1px solid #e5e7eb',
            background: isActive ? tab.color : '#fff',
            color: isActive ? '#fff' : '#374151',
            fontSize: '13px',
            fontWeight: isActive ? '700' : '500',
            cursor: 'pointer',
            transition: 'all 0.15s'
          }
        }, tab.label + ' (' + count + ')');
      })
    ),

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
            React.createElement('th', { style: { padding: '12px', textAlign: 'center', fontWeight: 'bold', color: '#6B21A8' } }, '분석 횟수'),
            React.createElement('th', { style: { padding: '12px', textAlign: 'left', fontWeight: 'bold', color: '#6B21A8' } }, '액션')
          )
        ),
        React.createElement('tbody', {},
          users.filter(function(u) { return roleFilter === 'all' || u.role === roleFilter; }).map(function(user, idx) {
            var isExpanded = expandedUserId === user.id;
            return React.createElement(React.Fragment, { key: user.id },
              React.createElement('tr', {
                style: {
                  backgroundColor: isExpanded ? '#EDE9FE' : (idx % 2 === 0 ? 'white' : '#F9F5FF'),
                  borderBottom: '1px solid #E9D5FF',
                  cursor: 'pointer'
                },
                onClick: function() { toggleLoginLogs(user.id); }
              },
                React.createElement('td', { style: { padding: '12px' } }, user.username),
                React.createElement('td', { style: { padding: '12px' } }, user.name),
                React.createElement('td', { style: { padding: '12px' } }, getRoleBadge(user.role)),
                React.createElement('td', { style: { padding: '12px' } }, getStatusBadge(user.status || 'active')),
                React.createElement('td', { style: { padding: '12px', fontSize: '12px', color: '#666' } }, new Date(user.created_at || user.createdAt).toLocaleDateString('ko-KR')),
                React.createElement('td', { style: { padding: '12px', textAlign: 'center' } },
                  React.createElement('span', {
                    style: {
                      display: 'inline-block',
                      minWidth: 36,
                      padding: '4px 10px',
                      borderRadius: 999,
                      fontSize: 13,
                      fontWeight: 700,
                      color: (analysisCounts[String(user.id)] || 0) > 0 ? '#6c5ce7' : '#94a3b8',
                      background: (analysisCounts[String(user.id)] || 0) > 0 ? '#ede9fe' : '#f1f5f9'
                    }
                  }, String(analysisCounts[String(user.id)] || 0) + '건')
                ),
                React.createElement('td', { style: { padding: '12px' } },
                  React.createElement('button', {
                    onClick: function(e) { e.stopPropagation(); handleOpenModal(user); },
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
                    onClick: function(e) { e.stopPropagation(); handleDeleteUser(user.id, user.username); },
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
              ),
              isExpanded && React.createElement('tr', { key: user.id + '-logs' },
                React.createElement('td', { colSpan: 7, style: { padding: '16px 20px', background: '#F5F3FF', borderBottom: '2px solid #C4B5FD' } },
                  React.createElement('div', { style: { fontSize: 13, fontWeight: 600, color: '#6B21A8', marginBottom: 8 } },
                    '📋 최근 7일 접속 이력 — ' + user.name + ' (' + user.username + ')'
                  ),
                  logsLoading
                    ? React.createElement('div', { style: { fontSize: 13, color: '#888' } }, '로딩 중...')
                    : loginLogs.length === 0
                      ? React.createElement('div', { style: { fontSize: 13, color: '#94a3b8' } }, '최근 7일간 접속 기록이 없습니다.')
                      : React.createElement('table', { style: { width: '100%', fontSize: 12, borderCollapse: 'collapse' } },
                          React.createElement('thead', null,
                            React.createElement('tr', null,
                              React.createElement('th', { style: { padding: '6px 10px', textAlign: 'left', color: '#6B21A8', borderBottom: '1px solid #DDD6FE' } }, '접속 일시'),
                              React.createElement('th', { style: { padding: '6px 10px', textAlign: 'left', color: '#6B21A8', borderBottom: '1px solid #DDD6FE' } }, 'IP 주소')
                            )
                          ),
                          React.createElement('tbody', null,
                            loginLogs.map(function(log) {
                              return React.createElement('tr', { key: log.id },
                                React.createElement('td', { style: { padding: '5px 10px', borderBottom: '1px solid #EDE9FE' } },
                                  new Date(log.login_at).toLocaleString('ko-KR')
                                ),
                                React.createElement('td', { style: { padding: '5px 10px', borderBottom: '1px solid #EDE9FE', color: '#64748b' } },
                                  log.ip_address || '-'
                                )
                              );
                            })
                          )
                        )
                )
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
