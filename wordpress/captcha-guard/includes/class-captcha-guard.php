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

		// 设置页"测试连接"（admin-ajax，仅管理员可触发）。
		add_action( 'wp_ajax_captcha_guard_test', array( $this, 'ajax_test_connection' ) );

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
			// 表单评论提交路径。
			add_action( 'pre_comment_on_post', array( $this, 'check_comment_captcha' ) );
			// REST API 创建评论路径（/wp-json/wp/v2/comments）。
			add_filter( 'rest_pre_insert_comment', array( $this, 'check_rest_comment_captcha' ), 10, 2 );
		}
		if ( $this->integration_enabled( 'lostpassword' ) ) {
			add_action( 'lostpassword_post', array( $this, 'check_lostpassword_captcha' ) );
		}
	}

	/**
	 * 登录校验。仅在 wp-login.php 表单提交路径生效；XML-RPC 认证请求一律拒绝
	 * （XML-RPC 无法携带验证码，是暴力破解的高危入口）。
	 *
	 * @param WP_User|WP_Error|null $user     认证结果。
	 * @param string                $username 用户名。
	 * @param string                $password 密码。
	 * @return WP_User|WP_Error
	 */
	public function check_login_captcha( $user, $username, $password ) {
		if ( defined( 'XMLRPC_REQUEST' ) && XMLRPC_REQUEST ) {
			return new WP_Error(
				'cg_xmlrpc_blocked',
				__( 'XML-RPC 登录已被验证码保护禁用，请通过网页登录。', 'captcha-guard' )
			);
		}
		if ( empty( $_POST['log'] ) || empty( $_POST['pwd'] ) ) {
			// 非 wp-login.php 表单路径（如 REST 认证），保持原样。
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
	 * 表单评论校验。
	 */
	public function check_comment_captcha() {
		$result = $this->verify()->check( isset( $_POST['cg_pass_token'] ) ? sanitize_text_field( wp_unslash( $_POST['cg_pass_token'] ) ) : '' );
		if ( is_wp_error( $result ) ) {
			wp_die( esc_html( $result->get_error_message() ), esc_html__( '安全验证未通过', 'captcha-guard' ), array( 'response' => 403 ) );
		}
	}

	/**
	 * REST API 创建评论校验（返回 WP_Error 时 REST 以 400 响应）。
	 *
	 * @param array          $prepared_comment 准备写入的评论数据。
	 * @param WP_REST_Request $request         当前请求。
	 * @return array|WP_Error
	 */
	public function check_rest_comment_captcha( $prepared_comment, $request ) {
		$result = $this->verify()->check( $request->get_param( 'cg_pass_token' ) );
		if ( is_wp_error( $result ) ) {
			return $result;
		}
		return $prepared_comment;
	}

	/**
	 * AJAX：测试连接（设置页按钮调用）。
	 */
	public function ajax_test_connection() {
		check_ajax_referer( 'captcha_guard_test', 'nonce' );
		if ( ! current_user_can( 'manage_options' ) ) {
			wp_send_json_error( array( 'msg' => __( '权限不足', 'captcha-guard' ) ), 403 );
		}
		wp_send_json( $this->run_connection_test() );
	}

	/**
	 * 连接测试：服务连通性 / API Key / PASS_TOKEN_SECRET 一致性 / SDK 地址。
	 *
	 * @return array
	 */
	private function run_connection_test() {
		$base   = rtrim( (string) $this->option( 'api_base_url' ), '/' );
		$key    = (string) $this->option( 'api_key' );
		$secret = (string) $this->option( 'pass_token_secret' );
		$sdk    = (string) $this->option( 'sdk_url' );
		if ( '' === $sdk ) {
			$sdk = $base . '/static/captcha-sdk.js';
		}

		$checks = array();

		$checks[] = array(
			'ok'     => '' !== $base,
			'label'  => __( 'API 服务地址', 'captcha-guard' ),
			'detail' => '' !== $base ? $base : __( '未填写（同域部署填域名，跨域填完整服务地址）', 'captcha-guard' ),
		);
		$checks[] = array(
			'ok'     => '' !== $key,
			'label'  => __( 'API Key', 'captcha-guard' ),
			'detail' => '' !== $key ? __( '已填写', 'captcha-guard' ) : __( '未填写', 'captcha-guard' ),
		);
		$checks[] = array(
			'ok'     => '' !== $secret,
			'label'  => __( 'PASS_TOKEN_SECRET', 'captcha-guard' ),
			'detail' => '' !== $secret ? __( '已填写', 'captcha-guard' ) : __( '未填写（需填写验证码服务端 SECRET_KEY 或 PASS_TOKEN_SECRET）', 'captcha-guard' ),
		);

		if ( '' !== $base && '' !== $key ) {
			$test_url = $base . '/api/v1/captcha/test';
			$host     = wp_parse_url( $test_url, PHP_URL_HOST );
			$filter   = $this->allow_external_host( $host );
			$resp     = wp_remote_post(
				$test_url,
				array(
					'timeout' => 10,
					'headers' => array(
						'X-API-Key'    => $key,
						'Content-Type' => 'application/json',
					),
					'body'    => '{}',
				)
			);
			remove_filter( 'http_request_host_is_external', $filter );

			if ( is_wp_error( $resp ) ) {
				$checks[] = array(
					'ok'     => false,
					'label'  => __( '验证码服务连通性', 'captcha-guard' ),
					'detail' => __( '无法连接：', 'captcha-guard' ) . $resp->get_error_message(),
				);
			} else {
				$code = (int) wp_remote_retrieve_response_code( $resp );
				$body = json_decode( wp_remote_retrieve_body( $resp ), true );
				if ( 200 === $code && is_array( $body ) && ! empty( $body['ok'] ) && isset( $body['data']['pass_token'] ) ) {
					$checks[] = array(
						'ok'     => true,
						'label'  => __( '验证码服务连通性 + API Key', 'captcha-guard' ),
						'detail' => __( '接口响应正常', 'captcha-guard' ),
					);

					$payload = Captcha_Guard_Verify::verify_jwt( $body['data']['pass_token'], $secret );
					if ( '' === $secret ) {
						// 未填写密钥已在前面报告。
					} elseif ( is_array( $payload ) && 'passed' === $payload['captcha'] ) {
						$checks[] = array(
							'ok'     => true,
							'label'  => __( 'PASS_TOKEN_SECRET 一致性', 'captcha-guard' ),
							'detail' => __( '服务端签名可被插件密钥验证（', 'captcha-guard' )
								. ( ! empty( $body['data']['server_secret_explicit'] )
									? __( '服务端显式配置 PASS_TOKEN_SECRET', 'captcha-guard' )
									: __( '服务端回退使用 SECRET_KEY', 'captcha-guard' ) )
								. __( '）', 'captcha-guard' ),
						);
					} else {
						$checks[] = array(
							'ok'     => false,
							'label'  => __( 'PASS_TOKEN_SECRET 一致性', 'captcha-guard' ),
							'detail' => __( '密钥不匹配：插件填写的密钥无法验证服务端签名', 'captcha-guard' ),
						);
					}
				} elseif ( 404 === $code ) {
					$checks[] = array(
						'ok'     => false,
						'label'  => __( '验证码服务连通性', 'captcha-guard' ),
						'detail' => __( '接口不存在：验证码服务版本过低，请升级到 v2.2.0+', 'captcha-guard' ),
					);
				} elseif ( 401 === $code ) {
					$checks[] = array(
						'ok'     => false,
						'label'  => __( 'API Key 有效性', 'captcha-guard' ),
						'detail' => __( '无效或缺失 API Key：服务端数据库中不存在该 Key 或已被禁用', 'captcha-guard' ),
					);
				} else {
					$checks[] = array(
						'ok'     => false,
						'label'  => __( '验证码服务连通性', 'captcha-guard' ),
						'detail' => 'HTTP ' . $code . '：'
							. ( is_array( $body ) && isset( $body['msg'] ) ? $body['msg'] : __( '未知响应', 'captcha-guard' ) ),
					);
				}
			}
		}

		if ( '' !== $sdk ) {
			$host   = wp_parse_url( $sdk, PHP_URL_HOST );
			$filter = $this->allow_external_host( $host );
			$head   = wp_remote_head( $sdk, array( 'timeout' => 10, 'redirection' => 3 ) );
			remove_filter( 'http_request_host_is_external', $filter );
			if ( is_wp_error( $head ) ) {
				$checks[] = array(
					'ok'     => false,
					'label'  => __( 'SDK 脚本', 'captcha-guard' ),
					'detail' => __( '无法访问：', 'captcha-guard' ) . $head->get_error_message(),
				);
			} else {
				$hcode = (int) wp_remote_retrieve_response_code( $head );
				if ( $hcode >= 200 && $hcode < 400 ) {
					$checks[] = array(
						'ok'     => true,
						'label'  => __( 'SDK 脚本', 'captcha-guard' ),
						'detail' => 'HTTP ' . $hcode,
					);
				} else {
					$checks[] = array(
						'ok'     => false,
						'label'  => __( 'SDK 脚本', 'captcha-guard' ),
						'detail' => 'HTTP ' . $hcode . '，' . __( '请检查 SDK 地址', 'captcha-guard' ),
					);
				}
			}
		}

		$all_ok = ! in_array( false, wp_list_pluck( $checks, 'ok' ), true );
		return array(
			'ok'     => $all_ok,
			'checks' => $checks,
		);
	}

	/**
	 * 放行指定主机的外部请求（仅用于本次测试，解决 WP 默认阻止 localhost 出站的问题）。
	 *
	 * @param string $host 目标主机。
	 * @return Closure 传入 remove_filter 的过滤函数。
	 */
	private function allow_external_host( $host ) {
		$filter = function ( $allow, $candidate ) use ( $host ) {
			if ( null !== $host && $candidate === $host ) {
				return true;
			}
			return $allow;
		};
		add_filter( 'http_request_host_is_external', $filter, 10, 2 );
		return $filter;
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
