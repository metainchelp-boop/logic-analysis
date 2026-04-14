window.ReportsPage = function ReportsPage(props) {
  var useState = React.useState;
  var useEffect = React.useEffect;

  var _useState = useState([]);
  var reports = _useState[0];
  var setReports = _useState[1];

  var _useState2 = useState(1);
  var currentPage = _useState2[0];
  var setCurrentPage = _useState2[1];

  var _useState3 = useState(0);
  var totalPages = _useState3[0];
  var setTotalPages = _useState3[1];

  var _useState4 = useState(false);
  var showModal = _useState4[0];
  var setShowModal = _useState4[1];

  var _useState5 = useState(false);
  var loading = _useState5[0];
  var setLoading = _useState5[1];

  var _useState6 = useState([]);
  var clients = _useState6[0];
  var setClients = _useState6[1];

  var _useState7 = useState('');
  var formKeyword = _useState7[0];
  var setFormKeyword = _useState7[1];

  var _useState8 = useState('');
  var formUrl = _useState8[0];
  var setFormUrl = _useState8[1];

  var _useState9 = useState('');
  var formClient = _useState9[0];
  var setFormClient = _useState9[1];

  var _useState10 = useState('');
  var formTitle = _useState10[0];
  var setFormTitle = _useState10[1];

  var _useState11 = useState(null);
  var generatedLink = _useState11[0];
  var setGeneratedLink = _useState11[1];

  var _useState12 = useState('');
  var statusMessage = _useState12[0];
  var setStatusMessage = _useState12[1];

  useEffect(function() {
    fetchReports(1);
    fetchClients();
  }, []);

  function fetchReports(page) {
    setLoading(true);
    fetch('/api/reports?page=' + page + '&per_page=20', {
      headers: {
        'Authorization': 'Bearer ' + props.token
      }
    })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        setReports(data.reports || []);
        setTotalPages(data.total_pages || 1);
        setCurrentPage(page);
        setLoading(false);
      })
      .catch(function(e) {
        console.error('리포트 조회 오류:', e);
        setLoading(false);
      });
  }

  function fetchClients() {
    fetch('/api/clients', {
      headers: {
        'Authorization': 'Bearer ' + props.token
      }
    })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        setClients(data.clients || []);
      })
      .catch(function(e) {
        console.error('광고주 조회 오류:', e);
      });
  }

  function handleGenerate() {
    if (!formKeyword.trim()) {
      setStatusMessage('키워드는 필수입니다.');
      return;
    }

    var payload = {
      keyword: formKeyword,
      product_url: formUrl || null,
      client_id: formClient || null,
      title: formTitle || formKeyword
    };

    setLoading(true);
    setStatusMessage('보고서 생성 중...');

    fetch('/api/reports/generate', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + props.token,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.hash) {
          var shareLink = window.location.origin + '/api/reports/view/' + data.hash;
          setGeneratedLink(shareLink);
          setStatusMessage('보고서가 생성되었습니다!');
          setTimeout(function() {
            setShowModal(false);
            setFormKeyword('');
            setFormUrl('');
            setFormClient('');
            setFormTitle('');
            setGeneratedLink(null);
            setStatusMessage('');
            fetchReports(1);
            setLoading(false);
          }, 2000);
        } else {
          setStatusMessage('생성 실패: ' + (data.error || '알 수 없는 오류'));
          setLoading(false);
        }
      })
      .catch(function(e) {
        setStatusMessage('오류: ' + e.message);
        setLoading(false);
      });
  }

  function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(function() {
      setStatusMessage('링크가 복사되었습니다!');
      setTimeout(function() { setStatusMessage(''); }, 2000);
    });
  }

  function deleteReport(reportId) {
    if (!confirm('정말 삭제하시겠습니까?')) return;

    fetch('/api/reports/' + reportId, {
      method: 'DELETE',
      headers: {
        'Authorization': 'Bearer ' + props.token
      }
    })
      .then(function(r) { return r.json(); })
      .then(function() {
        fetchReports(currentPage);
      })
      .catch(function(e) {
        console.error('삭제 오류:', e);
      });
  }

  var styles = {
    container: {
      padding: '20px',
      maxWidth: '1200px',
      margin: '0 auto',
      fontFamily: 'Arial, sans-serif'
    },
    header: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: '30px'
    },
    title: {
      fontSize: '28px',
      fontWeight: 'bold',
      color: '#333'
    },
    button: {
      padding: '10px 20px',
      backgroundColor: '#8B5CF6',
      color: 'white',
      border: 'none',
      borderRadius: '6px',
      cursor: 'pointer',
      fontSize: '14px',
      fontWeight: 'bold'
    },
    table: {
      width: '100%',
      borderCollapse: 'collapse',
      backgroundColor: 'white',
      borderRadius: '8px',
      overflow: 'hidden',
      boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
    },
    th: {
      backgroundColor: '#8B5CF6',
      color: 'white',
      padding: '12px',
      textAlign: 'left',
      fontWeight: 'bold'
    },
    td: {
      padding: '12px',
      borderBottom: '1px solid #e0e0e0'
    },
    modal: {
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      backgroundColor: 'rgba(0,0,0,0.5)',
      display: showModal ? 'flex' : 'none',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1000
    },
    modalContent: {
      backgroundColor: 'white',
      padding: '30px',
      borderRadius: '8px',
      width: '90%',
      maxWidth: '500px',
      boxShadow: '0 4px 12px rgba(0,0,0,0.2)'
    },
    formGroup: {
      marginBottom: '15px'
    },
    label: {
      display: 'block',
      marginBottom: '5px',
      fontWeight: 'bold',
      color: '#333'
    },
    input: {
      width: '100%',
      padding: '8px',
      border: '1px solid #ddd',
      borderRadius: '4px',
      fontSize: '14px',
      boxSizing: 'border-box'
    },
    pagination: {
      display: 'flex',
      justifyContent: 'center',
      gap: '5px',
      marginTop: '20px'
    },
    pageBtn: {
      padding: '6px 12px',
      border: '1px solid #8B5CF6',
      backgroundColor: 'white',
      color: '#8B5CF6',
      cursor: 'pointer',
      borderRadius: '4px',
      fontSize: '12px'
    },
    pageBtnActive: {
      backgroundColor: '#8B5CF6',
      color: 'white'
    },
    actionBtn: {
      padding: '6px 12px',
      marginRight: '8px',
      fontSize: '12px',
      cursor: 'pointer',
      border: 'none',
      borderRadius: '4px',
      backgroundColor: '#f0f0f0'
    },
    deleteBtn: {
      backgroundColor: '#ff6b6b',
      color: 'white'
    },
    spinner: {
      display: 'inline-block',
      width: '20px',
      height: '20px',
      border: '3px solid #f3f3f3',
      borderTop: '3px solid #8B5CF6',
      borderRadius: '50%',
      animation: 'spin 1s linear infinite'
    },
    shareLink: {
      padding: '10px',
      backgroundColor: '#f5f5f5',
      borderRadius: '4px',
      marginTop: '10px',
      wordBreak: 'break-all',
      fontSize: '12px'
    }
  };

  return React.createElement('div', {style: styles.container},
    React.createElement('style', null, '@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }'),
    React.createElement('div', {style: styles.header},
      React.createElement('h1', {style: styles.title}, '📊 보고서 관리'),
      React.createElement('button', {
        style: styles.button,
        onClick: function() { setShowModal(true); }
      }, '새 보고서 생성')
    ),

    loading && !showModal ? React.createElement('div', {style: {textAlign: 'center'}},
      React.createElement('div', {style: styles.spinner})
    ) : React.createElement('table', {style: styles.table},
      React.createElement('thead', null,
        React.createElement('tr', null,
          React.createElement('th', {style: styles.th}, '제목'),
          React.createElement('th', {style: styles.th}, '키워드'),
          React.createElement('th', {style: styles.th}, '광고주'),
          React.createElement('th', {style: styles.th}, '조회수'),
          React.createElement('th', {style: styles.th}, '생성일'),
          React.createElement('th', {style: styles.th}, '액션')
        )
      ),
      React.createElement('tbody', null,
        reports.map(function(report) {
          return React.createElement('tr', {key: report.id},
            React.createElement('td', {style: styles.td}, report.title),
            React.createElement('td', {style: styles.td}, report.keyword),
            React.createElement('td', {style: styles.td}, report.client_name || '-'),
            React.createElement('td', {style: styles.td}, report.views || 0),
            React.createElement('td', {style: styles.td}, new Date(report.created_at).toLocaleDateString('ko-KR')),
            React.createElement('td', {style: styles.td},
              React.createElement('button', {
                style: styles.actionBtn,
                onClick: function() { copyToClipboard(window.location.origin + '/api/reports/view/' + report.hash); }
              }, '공유 링크 복사'),
              React.createElement('button', {
                style: styles.actionBtn,
                onClick: function() { window.open('/api/reports/view/' + report.hash); }
              }, '보기'),
              React.createElement('button', {
                style: Object.assign({}, styles.actionBtn, styles.deleteBtn),
                onClick: function() { deleteReport(report.id); }
              }, '삭제')
            )
          );
        })
      )
    ),

    React.createElement('div', {style: styles.pagination},
      Array.from({length: totalPages}).map(function(_, i) {
        var pageNum = i + 1;
        return React.createElement('button', {
          key: pageNum,
          style: Object.assign({}, styles.pageBtn, pageNum === currentPage ? styles.pageBtnActive : {}),
          onClick: function() { fetchReports(pageNum); }
        }, pageNum);
      })
    ),

    React.createElement('div', {style: styles.modal},
      React.createElement('div', {style: styles.modalContent},
        React.createElement('h2', null, '새 보고서 생성'),

        React.createElement('div', {style: styles.formGroup},
          React.createElement('label', {style: styles.label}, '키워드 (필수)'),
          React.createElement('input', {
            style: styles.input,
            type: 'text',
            value: formKeyword,
            onChange: function(e) { setFormKeyword(e.target.value); },
            placeholder: '예: 무선 이어폰'
          })
        ),

        React.createElement('div', {style: styles.formGroup},
          React.createElement('label', {style: styles.label}, '상품 URL (선택)'),
          React.createElement('input', {
            style: styles.input,
            type: 'text',
            value: formUrl,
            onChange: function(e) { setFormUrl(e.target.value); },
            placeholder: 'https://...'
          })
        ),

        React.createElement('div', {style: styles.formGroup},
          React.createElement('label', {style: styles.label}, '광고주 (선택)'),
          React.createElement('select', {
            style: styles.input,
            value: formClient,
            onChange: function(e) { setFormClient(e.target.value); }
          },
            React.createElement('option', {value: ''}, '선택하지 않음'),
            clients.map(function(c) {
              return React.createElement('option', {key: c.id, value: c.id}, c.name);
            })
          )
        ),

        React.createElement('div', {style: styles.formGroup},
          React.createElement('label', {style: styles.label}, '제목'),
          React.createElement('input', {
            style: styles.input,
            type: 'text',
            value: formTitle,
            onChange: function(e) { setFormTitle(e.target.value); },
            placeholder: '보고서 제목'
          })
        ),

        statusMessage && React.createElement('div', {style: {
          padding: '10px',
          marginBottom: '10px',
          backgroundColor: '#e3f2fd',
          borderRadius: '4px',
          fontSize: '14px',
          color: '#1976d2'
        }}, statusMessage),

        generatedLink && React.createElement('div', {style: styles.shareLink},
          '공유 링크: ',
          React.createElement('br', null),
          generatedLink
        ),

        React.createElement('div', {style: {display: 'flex', gap: '10px', marginTop: '20px'}},
          React.createElement('button', {
            style: Object.assign({}, styles.button, {flex: 1}),
            onClick: handleGenerate,
            disabled: loading
          }, loading ? '생성 중...' : '생성'),
          React.createElement('button', {
            style: Object.assign({}, styles.button, {backgroundColor: '#999', flex: 1}),
            onClick: function() { setShowModal(false); setStatusMessage(''); setGeneratedLink(null); },
            disabled: loading
          }, '닫기')
        )
      )
    )
  );
};
