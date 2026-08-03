<?php
/**
 * Plugin Name: Captcha Guard（动态验证码）
 * Description: 对接动态验证码管理系统（captcha_system），在后台选择滑动/点选/文字验证方式，保护登录、注册、评论、找回密码等表单。
 * Version: 1.0.1
 * Author: chinachat
 * License: MIT
 * Text Domain: captcha-guard
 * Requires at least: 5.8
 * Requires PHP: 7.4
 *
 * @package Captcha_Guard
 */

defined( 'ABSPATH' ) || exit;

define( 'CG_VERSION', '1.0.1' );
define( 'CG_PLUGIN_FILE', __FILE__ );
define( 'CG_PLUGIN_DIR', plugin_dir_path( __FILE__ ) );
define( 'CG_PLUGIN_URL', plugin_dir_url( __FILE__ ) );
define( 'CG_OPTION', 'captcha_guard_options' );

require_once CG_PLUGIN_DIR . 'includes/class-captcha-guard.php';
require_once CG_PLUGIN_DIR . 'includes/class-captcha-guard-verify.php';
require_once CG_PLUGIN_DIR . 'includes/class-captcha-guard-settings.php';
require_once CG_PLUGIN_DIR . 'includes/class-captcha-guard-frontend.php';

/**
 * 获取插件单例。
 *
 * @return Captcha_Guard
 */
function captcha_guard() {
	static $instance = null;
	if ( null === $instance ) {
		$instance = new Captcha_Guard();
	}
	return $instance;
}

captcha_guard()->init();
