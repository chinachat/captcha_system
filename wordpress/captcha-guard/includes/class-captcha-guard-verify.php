<?php
/**
 * pass_token（JWT, HS256）校验：签名 + 过期 + 一次性使用。
 *
 * @package Captcha_Guard
 */

defined( 'ABSPATH' ) || exit;

class Captcha_Guard_Verify {

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
	 * 校验请求携带的 pass_token。
	 *
	 * @param string $token pass_token（JWT）。
	 * @return true|WP_Error
	 */
	public function check( $token ) {
		$message = (string) $this->guard->option( 'fail_message', '安全验证未通过，请重试。' );

		if ( ! is_string( $token ) || '' === $token ) {
			return new WP_Error( 'cg_captcha', $message );
		}

		$secret = (string) $this->guard->option( 'pass_token_secret' );
		if ( '' === $secret ) {
			return new WP_Error( 'cg_captcha', __( '未配置 pass_token 密钥，请在插件设置中填写验证码服务的 PASS_TOKEN_SECRET。', 'captcha-guard' ) );
		}

		$payload = self::verify_jwt( $token, $secret );
		if ( ! is_array( $payload ) || empty( $payload['captcha'] ) || 'passed' !== $payload['captcha'] ) {
			return new WP_Error( 'cg_captcha', $message );
		}

		// 一次性使用：同一 jti 在有效期内只能通过一次。
		$jti = isset( $payload['jti'] ) ? (string) $payload['jti'] : '';
		if ( '' !== $jti ) {
			$transient = 'cg_jti_' . md5( $jti );
			if ( get_transient( $transient ) ) {
				return new WP_Error( 'cg_captcha', __( '验证码已使用，请重新验证。', 'captcha-guard' ) );
			}
			set_transient( $transient, 1, 120 );
		}

		return true;
	}

	/**
	 * 校验 HS256 JWT 签名与过期时间（纯 PHP 实现，无第三方依赖）。
	 *
	 * @param string $token  JWT 字符串。
	 * @param string $secret 签名密钥。
	 * @return array|null 载荷数组，无效返回 null。
	 */
	public static function verify_jwt( $token, $secret ) {
		if ( ! is_string( $token ) || ! is_string( $secret ) || '' === $secret ) {
			return null;
		}
		$parts = explode( '.', $token );
		if ( 3 !== count( $parts ) ) {
			return null;
		}
		$payload = json_decode( self::b64url_decode( $parts[1] ), true );
		if ( ! is_array( $payload ) ) {
			return null;
		}
		if ( isset( $payload['exp'] ) && (int) $payload['exp'] <= time() ) {
			return null;
		}
		$signing_input = $parts[0] . '.' . $parts[1];
		$expected      = self::b64url_encode( hash_hmac( 'sha256', $signing_input, $secret, true ) );
		if ( ! hash_equals( $expected, $parts[2] ) ) {
			return null;
		}
		return $payload;
	}

	/**
	 * base64url 解码。
	 *
	 * @param string $data base64url 字符串。
	 * @return string
	 */
	private static function b64url_decode( $data ) {
		$raw = base64_decode( strtr( $data, '-_', '+/' ), true );
		return false === $raw ? '' : $raw;
	}

	/**
	 * base64url 编码。
	 *
	 * @param string $raw 原始字节。
	 * @return string
	 */
	private static function b64url_encode( $raw ) {
		return rtrim( strtr( base64_encode( $raw ), '+/', '-_' ), '=' );
	}
}
