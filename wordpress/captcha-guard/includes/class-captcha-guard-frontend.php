<?php
/**
 * 前端资源：SDK 加载与表单拦截配置。
 *
 * @package Captcha_Guard
 */

defined( 'ABSPATH' ) || exit;

class Captcha_Guard_Frontend {

	/**
	 * 核心实例。
	 *
	 * @var Captcha_Guard
	 */
	private $guard;

	/**
	 * 表单选择器映射。
	 *
	 * @var array
	 */
	private $form_map = array(
		'login'        => '#loginform',
		'register'     => '#registerform',
		'comment'      => '#commentform',
		'lostpassword' => '#lostpasswordform',
	);

	public function __construct( $guard ) {
		$this->guard = $guard;
	}

	/**
	 * 初始化。
	 */
	public function init() {
		// wp-login.php（登录/注册/找回密码）。
		add_action( 'login_enqueue_scripts', array( $this, 'enqueue_login' ) );
		// 普通页面（评论等）。
		add_action( 'wp_enqueue_scripts', array( $this, 'enqueue_front' ) );
	}

	/**
	 * 登录页资源。
	 */
	public function enqueue_login() {
		$config = $this->build_config( array( 'login', 'register', 'lostpassword' ) );
		if ( $config ) {
			$this->enqueue_assets( $config );
		}
	}

	/**
	 * 普通页面资源（仅评论表单需要时）。
	 */
	public function enqueue_front() {
		$config = $this->build_config( array( 'comment' ) );
		if ( $config ) {
			$this->enqueue_assets( $config );
		}
	}

	/**
	 * 组装并输出资源。
	 *
	 * @param array $wanted 候选位置。
	 */
	private function enqueue_assets( $config ) {
		wp_enqueue_script(
			'captcha-guard',
			CG_PLUGIN_URL . 'assets/captcha-guard.js',
			array(),
			CG_VERSION,
			true
		);
		wp_localize_script( 'captcha-guard', 'CG_CONFIG', $config );
	}

	/**
	 * 生成前端配置（仅包含当前页面实际启用的表单）。
	 *
	 * @param array $wanted 候选位置。
	 * @return array|false
	 */
	private function build_config( $wanted ) {
		$forms = array();
		foreach ( $wanted as $name ) {
			if ( $this->guard->integration_enabled( $name ) ) {
				$forms[ $name ] = $this->form_map[ $name ];
			}
		}
		if ( empty( $forms ) ) {
			return false;
		}

		$base = rtrim( (string) $this->guard->option( 'api_base_url' ), '/' );
		$sdk  = (string) $this->guard->option( 'sdk_url' );
		if ( '' === $sdk ) {
			$sdk = $base . '/static/captcha-sdk.js';
		}

		return array(
			'apiKey'              => (string) $this->guard->option( 'api_key' ),
			'type'                => (string) $this->guard->option( 'captcha_type', 'slider' ),
			'baseUrl'             => $base,
			'sdkUrl'              => $sdk,
			'forms'               => $forms,
			'failMessage'         => (string) $this->guard->option( 'fail_message' ),
			'bypassWhenUnavailable' => (bool) $this->guard->option( 'bypass_when_unavailable', 0 ),
		);
	}
}
