window.LoginPage = function LoginPage(props) {
  var React = window.React;
  var useState = React.useState;

  var username = useState('');
  var usernameValue = username[0];
  var setUsername = username[1];

  var password = useState('');
  var passwordValue = password[0];
  var setPassword = password[1];

  var error = useState('');
  var errorValue = error[0];
  var setError = error[1];

  var loading = useState(false);
  var loadingValue = loading[0];
  var setLoading = loading[1];

  var handleSubmit = function(e) {
    e.preventDefault();
    setError('');
    setLoading(true);

    if (!usernameValue.trim() || !passwordValue.trim()) {
      setError('아이디와 비밀번호를 입력해주세요');
      setLoading(false);
      return;
    }

    window.api.post('/auth/login', {
      username: usernameValue,
      password: passwordValue
    }).then(function(response) {
      setLoading(false);
      var data = response.data || response;
      if (props.onLogin) {
        props.onLogin(data.user, data.token);
      }
    }).catch(function(err) {
      setLoading(false);
      var message = '로그인에 실패했습니다';
      if (err.response && err.response.data && err.response.data.message) {
        message = err.response.data.message;
      } else if (err.detail) {
        message = err.detail;
      } else if (err.message) {
        message = err.message;
      }
      setError(message);
    });
  };

  var styles = {
    container: {
      minHeight: '100vh',
      background: 'linear-gradient(135deg, #6C5CE7 0%, #a29bfe 100%)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: '"Noto Sans KR", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      padding: '20px'
    },
    card: {
      background: 'white',
      borderRadius: '12px',
      boxShadow: '0 10px 40px rgba(0, 0, 0, 0.15)',
      padding: '48px 40px',
      width: '100%',
      maxWidth: '400px'
    },
    header: {
      textAlign: 'center',
      marginBottom: '40px'
    },
    logo: {
      fontSize: '48px',
      marginBottom: '16px'
    },
    title: {
      fontSize: '28px',
      fontWeight: '700',
      color: '#2d3436',
      marginBottom: '8px'
    },
    subtitle: {
      fontSize: '14px',
      color: '#636e72',
      marginBottom: '16px'
    },
    badge: {
      display: 'inline-block',
      background: '#6C5CE7',
      color: 'white',
      padding: '4px 12px',
      borderRadius: '20px',
      fontSize: '12px',
      fontWeight: '600'
    },
    form: {
      display: 'flex',
      flexDirection: 'column'
    },
    formGroup: {
      marginBottom: '20px'
    },
    inputWrapper: {
      display: 'flex',
      alignItems: 'center',
      border: '1px solid #dfe6e9',
      borderRadius: '8px',
      padding: '0 12px',
      transition: 'border-color 0.3s'
    },
    inputWrapperFocus: {
      borderColor: '#6C5CE7'
    },
    inputIcon: {
      marginRight: '12px',
      fontSize: '18px',
      color: '#6C5CE7'
    },
    input: {
      flex: 1,
      border: 'none',
      padding: '12px 0',
      fontSize: '14px',
      outline: 'none',
      fontFamily: 'inherit'
    },
    button: {
      background: '#6C5CE7',
      color: 'white',
      border: 'none',
      padding: '12px 24px',
      borderRadius: '8px',
      fontSize: '16px',
      fontWeight: '600',
      cursor: loadingValue ? 'not-allowed' : 'pointer',
      transition: 'background 0.3s',
      opacity: loadingValue ? 0.7 : 1,
      marginTop: '12px'
    },
    buttonHover: {
      background: '#5f3dc4'
    },
    error: {
      background: '#fff5f5',
      border: '1px solid #fab1a0',
      color: '#d63031',
      padding: '12px',
      borderRadius: '6px',
      fontSize: '14px',
      marginBottom: '20px',
      textAlign: 'center'
    },
    loadingText: {
      opacity: 0.7
    }
  };

  return React.createElement('div', { style: styles.container },
    React.createElement('div', { style: styles.card },
      React.createElement('div', { style: styles.header },
        React.createElement('img', { src: '/img/logo_light.png', alt: 'META INC', style: { height:48, width:'auto', marginBottom:16 } }),
        React.createElement('div', { style: styles.title }, '로직 분석'),
        React.createElement('div', { style: styles.subtitle }, '네이버 쇼핑 키워드 분석 & 순위 추적'),
        React.createElement('div', { style: { marginTop: '16px' } },
          React.createElement('span', { style: styles.badge }, (window.APP_VERSION || 'v3.9') + ' 에이전시')
        )
      ),
      errorValue && React.createElement('div', { style: styles.error }, errorValue),
      React.createElement('form', { style: styles.form, onSubmit: handleSubmit },
        React.createElement('div', { style: styles.formGroup },
          React.createElement('div', { style: styles.inputWrapper },
            React.createElement('span', { style: styles.inputIcon }, '👤'),
            React.createElement('input', {
              type: 'text',
              placeholder: '아이디',
              value: usernameValue,
              onChange: function(e) { setUsername(e.target.value); },
              style: styles.input,
              disabled: loadingValue
            })
          )
        ),
        React.createElement('div', { style: styles.formGroup },
          React.createElement('div', { style: styles.inputWrapper },
            React.createElement('span', { style: styles.inputIcon }, '🔒'),
            React.createElement('input', {
              type: 'password',
              placeholder: '비밀번호',
              value: passwordValue,
              onChange: function(e) { setPassword(e.target.value); },
              style: styles.input,
              disabled: loadingValue
            })
          )
        ),
        React.createElement('button', {
          type: 'submit',
          style: styles.button,
          disabled: loadingValue,
          onMouseEnter: function(e) {
            if (!loadingValue) e.target.style.background = styles.buttonHover.background;
          },
          onMouseLeave: function(e) {
            e.target.style.background = styles.button.background;
          }
        },
          loadingValue ? '로그인 중...' : '로그인'
        )
      )
    )
  );
};
