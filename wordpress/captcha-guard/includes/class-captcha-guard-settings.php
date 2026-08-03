<?php
/**
 * 后台设置页（Settings API）：验证方式选择、API 配置、集成位置。
 *
 * @package Captcha_Guard
 */

defined( 'ABSPATH' ) || exit;

class Captcha_Guard_Settings {

	/**
	 * 核心实例。
	 *
	 * @var Captcha_Guard
	 */
	private $guard;

	public function __construct( $guard ) {
		$this->guard = $guard;
	}

	/**
	 * 初始化。
	 */
	public function init() {
		add_action( 'admin_menu', array( $this, 'add_menu' ) );
		add_action( 'admin_init', array( $this, 'register_settings' ) );
		add_action( 'admin_enqueue_scripts', array( $this, 'enqueue_admin' ) );
	}

	/**
	 * 设置页专用资源（仅本页加载）。
	 *
	 * @param string $hook 当前后台页面。
	 */
	public function enqueue_admin( $hook ) {
		if ( 'settings_page_captcha-guard' !== $hook ) {
			return;
		}
		wp_enqueue_script(
			'captcha-guard-admin',
			CG_PLUGIN_URL . 'assets/captcha-guard-admin.js',
			array(),
			CG_VERSION,
			true
		);
		wp_localize_script(
			'captcha-guard-admin',
			'CG_TEST',
			array(
				'nonce'   => wp_create_nonce( 'captcha_guard_test' ),
				'ajaxurl' => admin_url( 'admin-ajax.php' ),
			)
		);
	}

	/**
	 * 添加设置菜单。
	 */
	public function add_menu() {
		add_options_page(
			__( 'Captcha Guard 设置', 'captcha-guard' ),
			__( 'Captcha Guard', 'captcha-guard' ),
			'manage_options',
			'captcha-guard',
			array( $this, 'render_page' )
		);
	}

	/**
	 * 注册设置项。
	 */
	public function register_settings() {
		register_setting( 'captcha_guard', CG_OPTION, array( 'sanitize_callback' => array( $this, 'sanitize' ) ) );

		add_settings_section(
			'cg_general',
			__( '基本设置', 'captcha-guard' ),
			array( $this, 'render_general_help' ),
			'captcha-guard'
		);

		add_settings_field(
			'enabled',
			__( '启用验证码', 'captcha-guard' ),
			array( $this, 'field_enabled' ),
			'captcha-guard',
			'cg_general'
		);
		add_settings_field(
			'captcha_type',
			__( '验证方式', 'captcha-guard' ),
			array( $this, 'field_type' ),
			'captcha-guard',
			'cg_general'
		);
		add_settings_field(
			'api_base_url',
			__( '验证码服务地址 (API Base URL)', 'captcha-guard' ),
			array( $this, 'field_base_url' ),
			'captcha-guard',
			'cg_general'
		);
		add_settings_field(
			'api_key',
			__( 'API Key', 'captcha-guard' ),
			array( $this, 'field_api_key' ),
			'captcha-guard',
			'cg_general'
		);
		add_settings_field(
			'pass_token_secret',
			__( 'PASS_TOKEN_SECRET', 'captcha-guard' ),
			array( $this, 'field_secret' ),
			'captcha-guard',
			'cg_general'
		);
		add_settings_field(
			'sdk_url',
			__( 'SDK 脚本地址', 'captcha-guard' ),
			array( $this, 'field_sdk_url' ),
			'captcha-guard',
			'cg_general'
		);
		add_settings_field(
			'fail_message',
			__( '失败提示文案', 'captcha-guard' ),
			array( $this, 'field_fail_message' ),
			'captcha-guard',
			'cg_general'
		);
		add_settings_field(
			'bypass_when_unavailable',
			__( '服务不可用时放行', 'captcha-guard' ),
			array( $this, 'field_bypass' ),
			'captcha-guard',
			'cg_general'
		);

		add_settings_section(
			'cg_integrations',
			__( '保护范围', 'captcha-guard' ),
			array( $this, 'render_integration_help' ),
			'captcha-guard'
		);
		add_settings_field(
			'integrations',
			__( '启用的表单', 'captcha-guard' ),
			array( $this, 'field_integrations' ),
			'captcha-guard',
			'cg_integrations'
		);
	}

	/**
	 * 渲染设置页。
	 */
	public function render_page() {
		if ( ! current_user_can( 'manage_options' ) ) {
			return;
		}
		?>
		<div class="wrap">
			<h1><?php esc_html_e( 'Captcha Guard（动态验证码）', 'captcha-guard' ); ?></h1>
			<form action="options.php" method="post">
				<?php
				settings_fields( 'captcha_guard' );
				do_settings_sections( 'captcha-guard' );
				submit_button();
				?>
			</form>
			<div style="margin-top:24px;max-width:640px;">
				<h2 style="margin-bottom:8px;"><?php esc_html_e( '连接测试', 'captcha-guard' ); ?></h2>
				<p><?php esc_html_e( '保存设置后点击下方按钮，验证插件与验证码服务的连通性、API Key 有效性及签名密钥是否一致。', 'captcha-guard' ); ?></p>
				<button type="button" id="cg-test-btn" class="button button-secondary"><?php esc_html_e( '测试连接', 'captcha-guard' ); ?></button>
				<span id="cg-test-status" style="margin-left:10px;font-weight:600;"></span>
				<ul id="cg-test-checks" style="margin-top:12px;"></ul>
			</div>
		</div>
		<?php
	}

	/**
	 * 数据清洗。
	 *
	 * @param array $input 原始输入。
	 * @return array
	 */
	public function sanitize( $input ) {
		$out = array();

		$out['enabled'] = empty( $input['enabled'] ) ? 0 : 1;

		$type = isset( $input['captcha_type'] ) ? $input['captcha_type'] : '';
		$out['captcha_type'] = in_array( $type, Captcha_Guard::CAPTCHA_TYPES, true ) ? $type : 'slider';

		$out['api_base_url']      = esc_url_raw( isset( $input['api_base_url'] ) ? (string) $input['api_base_url'] : '' );
		$out['api_key']           = sanitize_text_field( isset( $input['api_key'] ) ? (string) $input['api_key'] : '' );
		$out['pass_token_secret'] = sanitize_text_field( isset( $input['pass_token_secret'] ) ? (string) $input['pass_token_secret'] : '' );
		$out['sdk_url']           = esc_url_raw( isset( $input['sdk_url'] ) ? (string) $input['sdk_url'] : '' );
		$out['fail_message']      = sanitize_text_field( isset( $input['fail_message'] ) ? (string) $input['fail_message'] : '' );
		if ( '' === $out['fail_message'] ) {
			$out['fail_message'] = '安全验证未通过，请重试。';
		}
		$out['bypass_when_unavailable'] = empty( $input['bypass_when_unavailable'] ) ? 0 : 1;

		$out['integrations'] = array();
		if ( isset( $input['integrations'] ) && is_array( $input['integrations'] ) ) {
			foreach ( $input['integrations'] as $item ) {
				if ( in_array( $item, Captcha_Guard::INTEGRATIONS, true ) ) {
					$out['integrations'][] = $item;
				}
			}
		}
		if ( empty( $out['integrations'] ) ) {
			$out['integrations'] = array( 'login' );
		}

		return $out;
	}

	/**
	 * 通用设置说明。
	 */
	public function render_general_help() {
		echo '<p>' . esc_html__( '对接"动态验证码管理系统"（captcha_system）服务。需要在验证码服务端创建 API Key，并记录其 PASS_TOKEN_SECRET（未单独设置时即 SECRET_KEY）。', 'captcha-guard' ) . '</p>';
	}

	/**
	 * 保护范围说明。
	 */
	public function render_integration_help() {
		echo '<p>' . esc_html__( '选择需要保护的 WordPress 表单。提示：登录表单建议保留验证码，评论可仅对未登录用户启用（可按需关闭）。', 'captcha-guard' ) . '</p>';
	}

	/**
	 * 输出 value helper。
	 *
	 * @param string $key 配置键。
	 * @return string
	 */
	private function value( $key ) {
		return (string) $this->guard->option( $key );
	}

	public function field_enabled() {
		$checked = $this->guard->option( 'enabled', 0 ) ? ' checked="checked"' : '';
		echo '<label><input type="checkbox" name="' . esc_attr( CG_OPTION ) . '[enabled]" value="1"' . $checked . ' /> ' . esc_html__( '启用验证码保护', 'captcha-guard' ) . '</label>';
	}

	public function field_type() {
		$current = $this->guard->option( 'captcha_type', 'slider' );
		$labels  = array(
			'slider' => __( '滑动拼图验证码', 'captcha-guard' ),
			'click'  => __( '点选验证码', 'captcha-guard' ),
			'text'   => __( '文字验证码（旧接口）', 'captcha-guard' ),
		);
		echo '<select name="' . esc_attr( CG_OPTION ) . '[captcha_type]">';
		foreach ( Captcha_Guard::CAPTCHA_TYPES as $type ) {
			printf(
				'<option value="%1$s"%2$s>%3$s</option>',
				esc_attr( $type ),
				selected( $current, $type, false ),
				esc_html( isset( $labels[ $type ] ) ? $labels[ $type ] : $type )
			);
		}
		echo '</select>';
		echo '<p class="description">' . esc_html__( '选择前端弹窗使用的验证方式。', 'captcha-guard' ) . '</p>';
	}

	public function field_base_url() {
		printf(
			'<input type="url" class="regular-text code" name="%1$s[api_base_url]" value="%2$s" placeholder="https://captcha.example.com" />',
			esc_attr( CG_OPTION ),
			esc_attr( $this->value( 'api_base_url' ) )
		);
		echo '<p class="description">' . esc_html__( '验证码服务地址。与 WordPress 同域部署可留空（例如挂在 /captcha 子路径时填 https://你的域名/captcha）。', 'captcha-guard' ) . '</p>';
	}

	public function field_api_key() {
		printf(
			'<input type="password" class="regular-text code" name="%1$s[api_key]" value="%2$s" autocomplete="off" />',
			esc_attr( CG_OPTION ),
			esc_attr( $this->value( 'api_key' ) )
		);
		echo '<p class="description">' . esc_html__( '验证码服务的 API Key（前端 SDK 请求用，会暴露在页面中，建议专用低权限 Key）。', 'captcha-guard' ) . '</p>';
	}

	public function field_secret() {
		printf(
			'<input type="password" class="regular-text code" name="%1$s[pass_token_secret]" value="%2$s" autocomplete="off" />',
			esc_attr( CG_OPTION ),
			esc_attr( $this->value( 'pass_token_secret' ) )
		);
		echo '<p class="description">' . esc_html__( '可留空：留空时插件调用验证码服务在线校验接口（需 API Key，普通用户推荐）；填写则本地验签（离线、更快）。', 'captcha-guard' ) . '</p>';
	}

	public function field_sdk_url() {
		printf(
			'<input type="url" class="regular-text code" name="%1$s[sdk_url]" value="%2$s" placeholder="' . esc_attr( __( '留空自动：服务地址 + /static/captcha-sdk.js', 'captcha-guard' ) ) . '" />',
			esc_attr( CG_OPTION ),
			esc_attr( $this->value( 'sdk_url' ) )
		);
		echo '<p class="description">' . esc_html__( '前端 SDK（captcha-sdk.js）完整地址，一般无需修改。', 'captcha-guard' ) . '</p>';
	}

	public function field_fail_message() {
		printf(
			'<input type="text" class="regular-text" name="%1$s[fail_message]" value="%2$s" />',
			esc_attr( CG_OPTION ),
			esc_attr( $this->value( 'fail_message' ) )
		);
	}

	public function field_bypass() {
		$checked = $this->guard->option( 'bypass_when_unavailable', 0 ) ? ' checked="checked"' : '';
		echo '<label><input type="checkbox" name="' . esc_attr( CG_OPTION ) . '[bypass_when_unavailable]" value="1"' . $checked . ' /> ' . esc_html__( '验证码服务不可用时放行（仅建议调试阶段开启）', 'captcha-guard' ) . '</label>';
	}

	public function field_integrations() {
		$current = (array) $this->guard->option( 'integrations', array() );
		$labels  = array(
			'login'        => __( '登录表单', 'captcha-guard' ),
			'register'     => __( '注册表单', 'captcha-guard' ),
			'comment'      => __( '评论表单', 'captcha-guard' ),
			'lostpassword' => __( '找回密码表单', 'captcha-guard' ),
		);
		echo '<fieldset>';
		foreach ( Captcha_Guard::INTEGRATIONS as $name ) {
			printf(
				'<label style="display:block;margin:4px 0;"><input type="checkbox" name="%1$s[integrations][]" value="%2$s"%3$s /> %4$s</label>',
				esc_attr( CG_OPTION ),
				esc_attr( $name ),
				checked( in_array( $name, $current, true ), true, false ),
				esc_html( isset( $labels[ $name ] ) ? $labels[ $name ] : $name )
			);
		}
		echo '</fieldset>';
	}
}
