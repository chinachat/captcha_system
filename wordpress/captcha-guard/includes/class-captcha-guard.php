<?php
/**
 * 核心类：配置读写、服务端校验挂钩。
 *
 * @package Captcha_Guard
 */

defined( 'ABSPATH' ) || exit;

class Captcha_Guard {

	/**
	 * 允许的集成位置。
	 */
	const INTEGRATIONS = array( 'login', 'register', 'comment', 'lostpassword' );

	/**
	 * 验证方式。
	 */
	const CAPTCHA_TYPES = array( 'slider', 'click', 'text' );

	/**
	 * 默认配置。
	 *
	 * @var array
	 */
	private $defaults = array(
		'enabled'                 => 0,
		'captcha_type'            => 'slider',
		'api_base_url'            => '',
		'api_key'                 => '',
		'pass_token_secret'       => '',
		'sdk_url'                 => '',
		'integrations'            => array( 'login' ),
		'fail_message'            => '安全验证未通过，请重试。',
		'bypass_when_unavailable' => 0,
	);

	/**
	 * 子组件。
	 *
	 * @var Captcha_Guard_Verify|Captcha_Guard_Settings|Captcha_Guard_Frontend
	 */
	private $verify;
	private $settings;
	private $frontend;

	public function __construct() {
		$this->verify   = new Captcha_Guard_Verify( $this );
		$this->settings = new Captcha_Guard_Settings( $this );
		$this->frontend = new Captcha_Guard_Frontend( $this );
	}

	/**
	 * 初始化。
	 */
	public function init() {
		$this->settings->init();

		if ( $this->is_enabled() ) {
			$this->frontend->init();
			$this->register_hooks();
		}

		add_action( 'init', array( $this, 'load_textdomain' ) );
	}

	/**
	 * 读取配置项。
	 *
	 * @param string $key     配置键。
	 * @param mixed  $default 默认值。
	 * @return mixed
	 */
	public function option( $key, $default = null ) {
		$options = get_option( CG_OPTION, array() );
		if ( ! is_array( $options ) ) {
			$options = array();
		}
		if ( array_key_exists( $key, $options ) ) {
			return $options[ $key ];
		}
		if ( null !== $default ) {
			return $default;
		}
		return isset( $this->defaults[ $key ] ) ? $this->defaults[ $key ] : '';
	}

	/**
	 * 插件总开关。
	 *
	 * @return bool
	 */
	public function is_enabled() {
		return (bool) $this->option( 'enabled', 0 );
	}

	/**
	 * 指定集成位置是否启用。
	 *
	 * @param string $name 位置名（login/register/comment/lostpassword）。
	 * @return bool
	 */
	public function integration_enabled( $name ) {
		$integrations = (array) $this->option( 'integrations', array() );
		return in_array( $name, $integrations, true );
	}

	/**
	 * 获取默认配置。
	 *
	 * @return array
	 */
	public function defaults() {
		return $this->defaults;
	}

	/**
	 * 验证组件。
	 *
	 * @return Captcha_Guard_Verify
	 */
	public function verify() {
		return $this->verify;
	}

	/**
	 * 加载语言包。
	 */
	public function load_textdomain() {
		load_plugin_textdomain( 'captcha-guard', false, dirname( plugin_basename( CG_PLUGIN_FILE ) ) . '/languages' );
	}

	/**
	 * 注册服务端校验挂钩。
	 */
	private function register_hooks() {
		if ( $this->integration_enabled( 'login' ) ) {
			add_filter( 'authenticate', array( $this, 'check_login_captcha' ), 10, 3 );
		}
		if ( $this->integration_enabled( 'register' ) ) {
			add_filter( 'registration_errors', array( $this, 'check_register_captcha' ) );
		}
		if ( $this->integration_enabled( 'comment' ) ) {
			add_action( 'pre_comment_on_post', array( $this, 'check_comment_captcha' ) );
		}
		if ( $this->integration_enabled( 'lostpassword' ) ) {
			add_action( 'lostpassword_post', array( $this, 'check_lostpassword_captcha' ) );
		}
	}

	/**
	 * 登录校验。仅在 wp-login.php 表单提交路径生效，避免误伤 REST/XML-RPC。
	 *
	 * @param WP_User|WP_Error|null $user     认证结果。
	 * @param string                $username 用户名。
	 * @param string                $password 密码。
	 * @return WP_User|WP_Error
	 */
	public function check_login_captcha( $user, $username, $password ) {
		if ( empty( $_POST['log'] ) || empty( $_POST['pwd'] ) ) {
			// 非 wp-login.php 表单路径（如 REST、XML-RPC），保持原样。
			return $user;
		}
		$result = $this->verify()->check( isset( $_POST['cg_pass_token'] ) ? sanitize_text_field( wp_unslash( $_POST['cg_pass_token'] ) ) : '' );
		if ( is_wp_error( $result ) ) {
			return $result;
		}
		return $user;
	}

	/**
	 * 注册校验。
	 *
	 * @param WP_Error $errors 注册错误收集器。
	 * @return WP_Error
	 */
	public function check_register_captcha( $errors ) {
		if ( ! is_wp_error( $errors ) ) {
			$errors = new WP_Error();
		}
		$result = $this->verify()->check( isset( $_POST['cg_pass_token'] ) ? sanitize_text_field( wp_unslash( $_POST['cg_pass_token'] ) ) : '' );
		if ( is_wp_error( $result ) ) {
			$errors->add( 'cg_captcha', $result->get_error_message() );
		}
		return $errors;
	}

	/**
	 * 评论校验。
	 */
	public function check_comment_captcha() {
		$result = $this->verify()->check( isset( $_POST['cg_pass_token'] ) ? sanitize_text_field( wp_unslash( $_POST['cg_pass_token'] ) ) : '' );
		if ( is_wp_error( $result ) ) {
			wp_die( esc_html( $result->get_error_message() ), esc_html__( '安全验证未通过', 'captcha-guard' ), array( 'response' => 403 ) );
		}
	}

	/**
	 * 找回密码校验。
	 */
	public function check_lostpassword_captcha() {
		$result = $this->verify()->check( isset( $_POST['cg_pass_token'] ) ? sanitize_text_field( wp_unslash( $_POST['cg_pass_token'] ) ) : '' );
		if ( is_wp_error( $result ) ) {
			wp_die( esc_html( $result->get_error_message() ), esc_html__( '安全验证未通过', 'captcha-guard' ), array( 'response' => 403 ) );
		}
	}
}
