window.ClientsPage = function ClientsPage(props) {
  var useState = React.useState;
  var useEffect = React.useEffect;

  var currentUser = props.currentUser || {};
  var token = props.token;

  // State management
  var clientsState = useState([]);
  var clients = clientsState[0];
  var setClients = clientsState[1];

  var statsState = useState({ total: 0, active: 0, paused: 0, terminated: 0 });
  var stats = statsState[0];
  var setStats = statsState[1];

  var searchState = useState('');
  var search = searchState[0];
  var setSearch = searchState[1];

  var statusFilterState = useState('전체');
  var statusFilter = statusFilterState[0];
  var setStatusFilter = statusFilterState[1];

  var pageState = useState(1);
  var page = pageState[0];
  var setPage = pageState[1];

  var modalState = useState(false);
  var showModal = modalState[0];
  var setShowModal = modalState[1];

  var editingState = useState(null);
  var editing = editingState[0];
  var setEditing = editingState[1];

  var formState = useState({
    name: '',
    businessName: '',
    contact: '',
    phone: '',
    keywords: '',
    status: 'active'
  });
  var form = formState[0];
  var setForm = formState[1];

  var headers = { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' };

  // Fetch clients and stats
  useEffect(function() {
    fetchStats();
    fetchClients();
  }, [search, statusFilter, page]);

  var fetchStats = function() {
    fetch('/api/clients/stats/summary', { headers: headers })
      .then(function(res) { return res.json(); })
      .then(function(data) {
        setStats(data || { total: 0, active: 0, paused: 0, terminated: 0 });
      })
      .catch(function(err) { console.error('Stats fetch error:', err); });
  };

  var fetchClients = function() {
    var params = new URLSearchParams();
    params.append('page', page);
    params.append('limit', 20);
    if (search) params.append('search', search);
    if (statusFilter !== '전체') {
      var statusMap = { '활성': 'active', '일시중지': 'paused', '해지': 'terminated' };
      params.append('status', statusMap[statusFilter] || '');
    }

    fetch('/api/clients?' + params.toString(), { headers: headers })
      .then(function(res) { return res.json(); })
      .then(function(data) {
        setClients(data.items || []);
      })
      .catch(function(err) { console.error('Clients fetch error:', err); });
  };

  var openModal = function(client) {
    if (client) {
      setEditing(client);
      setForm({
        name: client.name || '',
        businessName: client.businessName || '',
        contact: client.contact || '',
        phone: client.phone || '',
        keywords: client.keywords || '',
        status: client.status || 'active'
      });
    } else {
      setEditing(null);
      setForm({
        name: '',
        businessName: '',
        contact: '',
        phone: '',
        keywords: '',
        status: 'active'
      });
    }
    setShowModal(true);
  };

  var closeModal = function() {
    setShowModal(false);
    setEditing(null);
  };

  var handleFormChange = function(field, value) {
    setForm(Object.assign({}, form, { [field]: value }));
  };

  var saveClient = function() {
    if (!form.name || !form.contact) {
      alert('광고주명과 담당자는 필수입니다.');
      return;
    }

    var method = editing ? 'PUT' : 'POST';
    var url = editing ? '/api/clients/' + editing.id : '/api/clients';
    var body = JSON.stringify(form);

    fetch(url, { method: method, headers: headers, body: body })
      .then(function(res) { return res.json(); })
      .then(function(data) {
        closeModal();
        fetchClients();
        fetchStats();
      })
      .catch(function(err) { console.error('Save error:', err); });
  };

  var deleteClient = function(clientId) {
    if (!window.confirm('이 광고주를 삭제하시겠습니까?')) return;

    fetch('/api/clients/' + clientId, { method: 'DELETE', headers: headers })
      .then(function(res) { return res.json(); })
      .then(function(data) {
        fetchClients();
        fetchStats();
      })
      .catch(function(err) { console.error('Delete error:', err); });
  };

  var getStatusBadgeColor = function(status) {
    if (status === 'active') return '#10b981';
    if (status === 'paused') return '#f59e0b';
    if (status === 'terminated') return '#ef4444';
    return '#9ca3af';
  };

  var getStatusLabel = function(status) {
    if (status === 'active') return '활성';
    if (status === 'paused') return '일시중지';
    if (status === 'terminated') return '해지';
    return status;
  };

  var canModify = currentUser.role === 'admin' || currentUser.role === 'manager';

  return React.createElement('div', { style: { padding: '20px', backgroundColor: '#f8f9fa', minHeight: '100vh' } },
    // Header
    React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '25px' } },
      React.createElement('h1', { style: { margin: 0, fontSize: '24px', color: '#1f2937' } }, '📋 광고주 관리'),
      canModify && React.createElement('button', {
        onClick: function() { openModal(null); },
        style: {
          padding: '10px 20px',
          backgroundColor: '#7c3aed',
          color: 'white',
          border: 'none',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '14px',
          fontWeight: '600'
        }
      }, '새 광고주 등록')
    ),

    // Stats bar
    React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '15px', marginBottom: '25px' } },
      [
        { label: '전체', value: stats.total },
        { label: '활성', value: stats.active },
        { label: '일시중지', value: stats.paused },
        { label: '해지', value: stats.terminated }
      ].map(function(stat, idx) {
        return React.createElement('div', {
          key: idx,
          style: {
            backgroundColor: 'white',
            padding: '15px 20px',
            borderRadius: '8px',
            boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
            textAlign: 'center'
          }
        },
          React.createElement('div', { style: { fontSize: '12px', color: '#6b7280', marginBottom: '8px' } }, stat.label),
          React.createElement('div', { style: { fontSize: '28px', fontWeight: '700', color: '#7c3aed' } }, stat.value)
        );
      })
    ),

    // Search & Filter bar
    React.createElement('div', { style: { display: 'flex', gap: '15px', marginBottom: '25px', flexWrap: 'wrap' } },
      React.createElement('input', {
        type: 'text',
        placeholder: '광고주명 또는 담당자 검색...',
        value: search,
        onChange: function(e) { setSearch(e.target.value); setPage(1); },
        style: {
          flex: 1,
          minWidth: '200px',
          padding: '10px 15px',
          border: '1px solid #d1d5db',
          borderRadius: '6px',
          fontSize: '14px'
        }
      }),
      React.createElement('select', {
        value: statusFilter,
        onChange: function(e) { setStatusFilter(e.target.value); setPage(1); },
        style: {
          padding: '10px 15px',
          border: '1px solid #d1d5db',
          borderRadius: '6px',
          fontSize: '14px',
          backgroundColor: 'white',
          cursor: 'pointer'
        }
      },
        React.createElement('option', null, '전체'),
        React.createElement('option', null, '활성'),
        React.createElement('option', null, '일시중지'),
        React.createElement('option', null, '해지')
      )
    ),

    // Client list table
    React.createElement('div', { style: { backgroundColor: 'white', borderRadius: '8px', boxShadow: '0 1px 3px rgba(0,0,0,0.1)', overflow: 'hidden' } },
      React.createElement('table', { style: { width: '100%', borderCollapse: 'collapse' } },
        React.createElement('thead', null,
          React.createElement('tr', { style: { backgroundColor: '#f3f4f6', borderBottom: '2px solid #e5e7eb' } },
            ['광고주명', '사업자명', '담당자', '연락처', '주요키워드', '상태', '등록일', '액션'].map(function(col, idx) {
              return React.createElement('th', {
                key: idx,
                style: {
                  padding: '12px 15px',
                  textAlign: 'left',
                  fontSize: '13px',
                  fontWeight: '600',
                  color: '#374151'
                }
              }, col);
            })
          )
        ),
        React.createElement('tbody', null,
          clients.map(function(client, idx) {
            return React.createElement('tr', {
              key: client.id,
              style: {
                borderBottom: '1px solid #e5e7eb',
                backgroundColor: idx % 2 === 0 ? '#ffffff' : '#f9fafb'
              }
            },
              React.createElement('td', { style: { padding: '12px 15px', fontSize: '14px' } }, client.name),
              React.createElement('td', { style: { padding: '12px 15px', fontSize: '14px', color: '#6b7280' } }, client.businessName || '-'),
              React.createElement('td', { style: { padding: '12px 15px', fontSize: '14px' } }, client.contact),
              React.createElement('td', { style: { padding: '12px 15px', fontSize: '14px', color: '#6b7280' } }, client.phone || '-'),
              React.createElement('td', { style: { padding: '12px 15px', fontSize: '13px', color: '#6b7280', maxWidth: '150px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, client.keywords || '-'),
              React.createElement('td', { style: { padding: '12px 15px' } },
                React.createElement('span', {
                  style: {
                    display: 'inline-block',
                    padding: '4px 12px',
                    backgroundColor: getStatusBadgeColor(client.status),
                    color: 'white',
                    borderRadius: '20px',
                    fontSize: '12px',
                    fontWeight: '600'
                  }
                }, getStatusLabel(client.status))
              ),
              React.createElement('td', { style: { padding: '12px 15px', fontSize: '13px', color: '#6b7280' } }, client.createdAt ? new Date(client.createdAt).toLocaleDateString('ko-KR') : '-'),
              React.createElement('td', { style: { padding: '12px 15px', display: 'flex', gap: '8px' } },
                canModify && React.createElement('button', {
                  onClick: function() { openModal(client); },
                  style: {
                    padding: '6px 12px',
                    backgroundColor: '#7c3aed',
                    color: 'white',
                    border: 'none',
                    borderRadius: '4px',
                    cursor: 'pointer',
                    fontSize: '12px'
                  }
                }, '수정'),
                canModify && React.createElement('button', {
                  onClick: function() { deleteClient(client.id); },
                  style: {
                    padding: '6px 12px',
                    backgroundColor: '#ef4444',
                    color: 'white',
                    border: 'none',
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

    // Pagination
    React.createElement('div', { style: { display: 'flex', justifyContent: 'center', gap: '10px', marginTop: '20px' } },
      [1, 2, 3, 4, 5].map(function(p) {
        return React.createElement('button', {
          key: p,
          onClick: function() { setPage(p); },
          style: {
            padding: '8px 12px',
            backgroundColor: p === page ? '#7c3aed' : '#e5e7eb',
            color: p === page ? 'white' : '#374151',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
            fontSize: '14px',
            fontWeight: p === page ? '600' : '400'
          }
        }, p);
      })
    ),

    // Add/Edit Modal
    showModal && React.createElement('div', {
      style: {
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(0,0,0,0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000
      },
      onClick: closeModal
    },
      React.createElement('div', {
        style: {
          backgroundColor: 'white',
          borderRadius: '8px',
          padding: '30px',
          maxWidth: '500px',
          width: '90%',
          boxShadow: '0 20px 25px rgba(0,0,0,0.15)'
        },
        onClick: function(e) { e.stopPropagation(); }
      },
        React.createElement('h2', { style: { margin: '0 0 20px 0', fontSize: '20px', color: '#1f2937' } }, editing ? '광고주 수정' : '새 광고주 등록'),
        React.createElement('div', { style: { display: 'grid', gap: '15px', marginBottom: '20px' } },
          React.createElement('input', {
            type: 'text',
            placeholder: '광고주명 *',
            value: form.name,
            onChange: function(e) { handleFormChange('name', e.target.value); },
            style: { padding: '10px', border: '1px solid #d1d5db', borderRadius: '4px', fontSize: '14px' }
          }),
          React.createElement('input', {
            type: 'text',
            placeholder: '사업자명',
            value: form.businessName,
            onChange: function(e) { handleFormChange('businessName', e.target.value); },
            style: { padding: '10px', border: '1px solid #d1d5db', borderRadius: '4px', fontSize: '14px' }
          }),
          React.createElement('input', {
            type: 'text',
            placeholder: '담당자 *',
            value: form.contact,
            onChange: function(e) { handleFormChange('contact', e.target.value); },
            style: { padding: '10px', border: '1px solid #d1d5db', borderRadius: '4px', fontSize: '14px' }
          }),
          React.createElement('input', {
            type: 'text',
            placeholder: '연락처',
            value: form.phone,
            onChange: function(e) { handleFormChange('phone', e.target.value); },
            style: { padding: '10px', border: '1px solid #d1d5db', borderRadius: '4px', fontSize: '14px' }
          }),
          React.createElement('input', {
            type: 'text',
            placeholder: '주요키워드 (쉼표로 구분)',
            value: form.keywords,
            onChange: function(e) { handleFormChange('keywords', e.target.value); },
            style: { padding: '10px', border: '1px solid #d1d5db', borderRadius: '4px', fontSize: '14px' }
          }),
          React.createElement('select', {
            value: form.status,
            onChange: function(e) { handleFormChange('status', e.target.value); },
            style: { padding: '10px', border: '1px solid #d1d5db', borderRadius: '4px', fontSize: '14px', backgroundColor: 'white', cursor: 'pointer' }
          },
            React.createElement('option', { value: 'active' }, '활성'),
            React.createElement('option', { value: 'paused' }, '일시중지'),
            React.createElement('option', { value: 'terminated' }, '해지')
          )
        ),
        React.createElement('div', { style: { display: 'flex', gap: '10px', justifyContent: 'flex-end' } },
          React.createElement('button', {
            onClick: closeModal,
            style: {
              padding: '10px 20px',
              backgroundColor: '#e5e7eb',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '14px',
              fontWeight: '600'
            }
          }, '취소'),
          React.createElement('button', {
            onClick: saveClient,
            style: {
              padding: '10px 20px',
              backgroundColor: '#7c3aed',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '14px',
              fontWeight: '600'
            }
          }, '저장')
        )
      )
    )
  );
};
